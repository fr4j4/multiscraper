"""Main orchestrator: manages workers, queue, and output."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import aiohttp

from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.batcher import batch_jobs
from multiscraper.core.job import Job
from multiscraper.core.shutdown import ShutdownHandler
from multiscraper.core.supervisor import Supervisor
from multiscraper.models import (
    MediaFile,
    MediaRef,
    MediaType,
    Rom,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.output.csv_writer import CsvWriter
from multiscraper.output.db import Database
from multiscraper.providers.cascade import run_cascade
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.utils.fs import safe_download

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates workers, queue, and output for a scrape run."""

    def __init__(
        self,
        registry: ProviderRegistry,
        config: MultiscraperConfig,
        db_path: str,
        csv_path: Path,
        media_root: Path,
        orchestrator: OrchestratorConfig | None = None,
        progress_bar: object | None = None,
    ):
        self._registry = registry
        self._config = config
        self._orchestrator = orchestrator or OrchestratorConfig()
        self._db = Database(db_path)
        self._csv_writer = CsvWriter(
            csv_path, flush_every=self._orchestrator.csv_flush_every,
        )
        self._media_root = media_root
        self._shutdown = ShutdownHandler()
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._supervisor: Supervisor | None = None
        self._blocked_providers: set[str] = set()
        self._row_seq = 0
        self._http: aiohttp.ClientSession | None = None
        self._progress = progress_bar
        self._progress_lock = asyncio.Lock()
        self._progress_matched = 0
        self._progress_no_match = 0
        self._progress_errors = 0
        self._progress_last_rom = ""
        self._progress_last_provider = ""

    async def start(self, roms: list[Rom], systems: list[str]) -> str:
        """Start a scrape run. Returns the run_id."""
        await self._db.init()
        run_id = await self._db.create_run(
            config_json=self._config.model_dump(mode="json"),
        )
        await self._csv_writer.write_header()
        self._http = aiohttp.ClientSession()
        self._shutdown.install(asyncio.get_event_loop())

        batches = batch_jobs(
            roms, run_id, self._orchestrator.batch_size,
        )
        for batch in batches:
            for job in batch:
                await self._queue.put(job)

        self._supervisor = Supervisor(
            queue=self._queue,
            max_attempts=self._orchestrator.max_job_attempts,
            failure_window_sec=self._orchestrator.worker_failure_window_sec,
            failure_threshold=self._orchestrator.worker_failure_threshold,
        )

        try:
            n_workers = max(1, self._orchestrator.workers)
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._csv_writer_loop())
                for i in range(n_workers):
                    tg.create_task(self._worker_loop(f"W-{i:02d}"))
        finally:
            if self._http is not None:
                await self._http.close()
                self._http = None

        await self._csv_writer.close()
        await self._db.close()
        return run_id

    async def _worker_loop(self, worker_id: str) -> None:
        """Main worker loop: pull jobs, process, push results."""
        while not self._shutdown.is_set:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except TimeoutError:
                if self._queue.empty() and not self._shutdown.is_set:
                    return
                continue

            try:
                result = await self._process_job(job)
                self._row_seq += 1
                await self._csv_writer.write_row(
                    job.run_id, self._row_seq, job.batch_id, worker_id, result,
                )
                await self._update_progress(result, job)
            except Exception as exc:
                logger.exception(
                    "worker_died worker=%s job=%s", worker_id, job.job_id,
                )
                async with self._progress_lock:
                    if self._progress is not None:
                        self._progress_errors += 1
                        self._progress.update(1)  # type: ignore[attr-defined]
                        self._progress.set_postfix(  # type: ignore[attr-defined]
                            matched=self._progress_matched,
                            no_match=self._progress_no_match,
                            errors=self._progress_errors,
                        )
                if self._supervisor is not None:
                    await self._supervisor.report_failure(worker_id, job, exc)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: Job) -> ScrapedResult:
        """Process a single job: run cascade, download media, persist."""
        wanted = {
            MediaType.IMAGE,
            MediaType.THUMBNAIL,
            MediaType.VIDEO,
            MediaType.MARQUEE,
            MediaType.BOX3D,
            MediaType.BACKCOVER,
            MediaType.FANART,
            MediaType.MANUAL,
            MediaType.MIXIMAGE,
            MediaType.LOGO,
        }

        cascade_result = await run_cascade(
            rom=job.rom,
            registry=self._registry,
            match_threshold=self._config.provider_defaults.match_threshold,
            blocked_providers=self._blocked_providers,
            wanted_media=wanted,
        )
        media_files: list[MediaFile] = []
        if cascade_result.media and self._http is not None:
            media_files = await self._download_media(
                job.rom.system, job.rom.normalized_name, cascade_result.media,
            )
        result = cascade_result.to_scraped_result(media_files=media_files)
        await self._persist_result(job, result)
        return result

    async def _persist_result(self, job: Job, result: ScrapedResult) -> None:
        """Persist a single scraped result to the database."""
        rom_id = await self._db.insert_rom(
            system=job.rom.system,
            rel_path=job.rom.rom_id.rel_path,
            raw_name=job.rom.raw_name,
            normalized_name=job.rom.normalized_name,
            size=job.rom.rom_id.size,
            mtime=job.rom.rom_id.mtime,
            crc32=job.rom.rom_id.crc32,
            sha1=job.rom.rom_id.sha1,
            cache_key=job.rom.rom_id.cache_key,
        )
        await self._db.insert_scrape_result(job.run_id, rom_id, result)

    async def _download_media(
        self,
        system: str,
        normalized_name: str,
        media: dict[MediaType, MediaRef],
    ) -> list[MediaFile]:
        """Download media files to media_root/<system>/<name>-<type>.<ext>."""
        if self._http is None:
            return []
        results: list[MediaFile] = []
        for media_type, ref in media.items():
            dest = self._media_path(
                system=system,
                normalized_name=normalized_name,
                media_type=media_type,
                ext=ref.ext,
            )
            try:
                await safe_download(str(ref.url), dest, self._http)
            except Exception as exc:
                logger.warning(
                    "media_download_failed url=%s dest=%s err=%s",
                    ref.url, dest, exc,
                )
                continue
            try:
                data = dest.read_bytes()
            except OSError as exc:
                logger.warning("media_read_failed path=%s err=%s", dest, exc)
                continue
            results.append(
                MediaFile(
                    type=media_type,
                    local_path=str(dest),
                    ext=ref.ext,
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    source=ref.source,
                )
            )
        return results

    def _media_path(
        self,
        *,
        system: str,
        normalized_name: str,
        media_type: MediaType,
        ext: str,
    ) -> Path:
        return (
            self._media_root
            / system
            / f"{normalized_name}-{media_type.value}.{ext}"
        )

    async def _update_progress(self, result: ScrapedResult, job: Job) -> None:
        """Update the progress bar with the latest result counters."""
        if self._progress is None:
            return
        async with self._progress_lock:
            status = result.status
            if status in (ScrapeStatus.OK, ScrapeStatus.PARTIAL):
                self._progress_matched += 1
            elif status == ScrapeStatus.NO_MATCH:
                self._progress_no_match += 1
            else:
                self._progress_errors += 1
            self._progress_last_rom = job.rom.normalized_name
            self._progress_last_provider = result.chosen_provider or "—"
            self._progress.update(1)  # type: ignore[attr-defined]
            self._progress.set_postfix(  # type: ignore[attr-defined]
                matched=self._progress_matched,
                no_match=self._progress_no_match,
                errors=self._progress_errors,
                last=f"{self._progress_last_rom} [{self._progress_last_provider}]",
            )

    async def _csv_writer_loop(self) -> None:
        """Consume result queue and write to CSV."""
        await self._queue.join()

    async def close(self) -> None:
        """Clean up resources."""
        await self._csv_writer.close()
