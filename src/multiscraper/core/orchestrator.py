"""Main orchestrator: manages workers, queue, and output."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp

from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.shutdown import ShutdownHandler
from multiscraper.core.supervisor import Supervisor
from multiscraper.models import (
    IdentifyMethod,
    MediaFile,
    MediaRef,
    MediaType,
    Rom,
    RomIdentifier,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.output.csv_writer import CsvWriter
from multiscraper.output.db import Database
from multiscraper.providers.base import AllProvidersBlocked, ProviderBlockedError
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
        db: Database,
        run_id: str,
        csv_path: Path,
        media_root: Path,
        orchestrator: OrchestratorConfig | None = None,
        progress_bar: object | None = None,
        skip_existing: bool = True,
        force_rescrape: bool = False,
    ):
        self._registry = registry
        self._config = config
        self._orchestrator = orchestrator or OrchestratorConfig()
        self._db = db
        self._run_id = run_id
        self._csv_writer = CsvWriter(
            csv_path, flush_every=self._orchestrator.csv_flush_every,
        )
        self._media_root = media_root
        self._shutdown = ShutdownHandler()
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
        self._skip_existing = skip_existing
        self._force_rescrape = force_rescrape
        self._discovery_done: asyncio.Event = asyncio.Event()
        self._provider_errors: dict[str, int] = {}
        self._aborted_reason: str = ""

    async def start(
        self,
        systems: list[str],
        discovery_done: asyncio.Event | None = None,
    ) -> None:
        """Start worker loops; they consume rows from discovered_roms.

        The DB connection must already be initialized and the
        discovered_roms table populated (see core/discovery.py). The
        function returns when all systems' queues are drained (or
        shutdown is requested). If discovery_done is provided, the
        workers wait for it before declaring the run drained.
        """
        await self._csv_writer.write_header()
        self._http = aiohttp.ClientSession()
        self._shutdown.install(asyncio.get_event_loop())

        self._supervisor = Supervisor(
            queue=asyncio.Queue(),
            max_attempts=self._orchestrator.max_job_attempts,
            failure_window_sec=self._orchestrator.worker_failure_window_sec,
            failure_threshold=self._orchestrator.worker_failure_threshold,
        )

        if discovery_done is None:
            self._discovery_done = asyncio.Event()
            self._discovery_done.set()
        else:
            self._discovery_done = discovery_done

        poll_interval = self._orchestrator.discovery_poll_interval_sec

        try:
            n_workers = max(1, self._orchestrator.workers)
            async with asyncio.TaskGroup() as tg:
                for i in range(n_workers):
                    tg.create_task(self._worker_loop(f"W-{i:02d}", systems, poll_interval))
        finally:
            if self._http is not None:
                await self._http.close()
                self._http = None

        await self._csv_writer.close()

    async def _worker_loop(
        self, worker_id: str, systems: list[str], poll_interval: float,
    ) -> None:
        """Main worker loop: claim rows from discovered_roms, process."""
        while not self._shutdown.is_set:
            claimed: dict[str, Any] | None = None
            for system in systems:
                row = await self._db.claim_one_discovered(self._run_id, system)
                if row is not None:
                    claimed = row
                    break
            if claimed is None:
                if self._discovery_done.is_set() and await self._all_drained(systems):
                    return
                await asyncio.sleep(poll_interval)
                continue

            try:
                result = await self._process_row(claimed)
                self._row_seq += 1
                await self._csv_writer.write_row(
                    self._run_id, self._row_seq, 0, worker_id, result,
                )
                await self._update_progress(result, claimed)
                await self._db.mark_completed(int(claimed["id"]))
            except AllProvidersBlocked:
                raise
            except ProviderBlockedError:
                raise
            except Exception as exc:
                logger.exception(
                    "worker_died worker=%s row=%s", worker_id, claimed["id"],
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
                await self._handle_failure(worker_id, claimed, exc)
            else:
                pass

    async def _all_drained(self, systems: list[str]) -> bool:
        """True if discovery finished and no rows are pending or claimed."""
        for system in systems:
            pending = await self._db.count_discovered(
                self._run_id, system=system, hash_status="pending",
            )
            if pending > 0:
                return False
            claimed = await self._db.count_discovered(
                self._run_id, system=system, hash_status="claimed",
            )
            if claimed > 0:
                return False
        return True

    async def _handle_failure(
        self, worker_id: str, row: dict[str, Any], exc: Exception,
    ) -> None:
        """Track failure on the supervisor and release the row back."""
        if self._supervisor is not None:
            quarantined = await self._supervisor.record_failure(worker_id)
            if quarantined:
                logger.error("worker_quarantined worker=%s", worker_id)
        await self._db.release_discovered(int(row["id"]), status="done")

    async def _process_row(self, row: dict[str, Any]) -> ScrapedResult:
        """Process a single claimed row: build Rom, run cascade, persist."""
        rom = self._row_to_rom(row)

        if self._skip_existing and not self._force_rescrape:
            cached_rom = await self._db.get_rom_by_cache_key(rom.rom_id.cache_key)
            if cached_rom is not None:
                cached = await self._db.get_cached_result(int(cached_rom["id"]))
                if cached is not None and cached["status"] in ("OK", "PARTIAL"):
                    result = ScrapedResult(
                        rom=rom,
                        status=ScrapeStatus.SKIPPED,
                        identify_method=IdentifyMethod.CRC32,
                        chosen_provider=cached.get("chosen_provider"),
                        match_score=cached.get("match_score"),
                        metadata=None,
                        media=[],
                        warnings=[],
                        error=None,
                        elapsed_ms=0,
                        fetched_at=datetime.now(tz=UTC),
                    )
                    await self._persist_result(rom, result)
                    return result
        wanted = {
            MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO,
            MediaType.MARQUEE, MediaType.BOX3D, MediaType.BACKCOVER,
            MediaType.FANART, MediaType.MANUAL, MediaType.MIXIMAGE, MediaType.LOGO,
        }

        try:
            cascade_result = await run_cascade(
                rom=rom,
                registry=self._registry,
                match_threshold=self._config.provider_defaults.match_threshold,
                blocked_providers=self._blocked_providers,
                wanted_media=wanted,
            )
        except AllProvidersBlocked as exc:
            self._aborted_reason = str(exc)
            logger.error("all_providers_blocked providers=%s", exc.blocked_providers)
            for provider_name in exc.blocked_providers:
                self._record_provider_error(provider_name)
            self._shutdown.set()
            raise
        except ProviderBlockedError as exc:
            self._record_provider_error(exc.provider_name)
            blocked_providers_snapshot = sorted(self._blocked_providers)
            self._aborted_reason = (
                f"provider {exc.provider_name!r} blocked: {exc.reason}"
            )
            logger.error(
                "provider_blocked_abort provider=%s reason=%s providers=%s",
                exc.provider_name, exc.reason, blocked_providers_snapshot,
            )
            self._shutdown.set()
            raise

        media_files: list[MediaFile] = []
        if cascade_result.media and self._http is not None:
            media_files = await self._download_media(
                rom.system, rom.normalized_name, cascade_result.media,
            )
        result = cascade_result.to_scraped_result(media_files=media_files)
        await self._persist_result(rom, result)
        return result

    def _row_to_rom(self, row: dict[str, Any]) -> Rom:
        rom_id = RomIdentifier(
            rel_path=row["rel_path"],
            size=int(row["size"]),
            mtime=int(row["mtime"]),
            crc32=row.get("crc32"),
            sha1=row.get("sha1"),
            cache_key=row.get("cache_key") or "",
        )
        return Rom(
            system=row["system"],
            rom_id=rom_id,
            raw_name=row["raw_name"],
            normalized_name=row["normalized_name"],
        )

    async def _persist_result(self, rom: Rom, result: ScrapedResult) -> None:
        """Persist a single scraped result to the database."""
        rom_id = await self._db.insert_rom(
            system=rom.system,
            rel_path=rom.rom_id.rel_path,
            raw_name=rom.raw_name,
            normalized_name=rom.normalized_name,
            size=rom.rom_id.size,
            mtime=rom.rom_id.mtime,
            crc32=rom.rom_id.crc32,
            sha1=rom.rom_id.sha1,
            cache_key=rom.rom_id.cache_key,
        )
        await self._db.insert_scrape_result(self._run_id, rom_id, result)

    def _record_provider_error(self, provider_name: str) -> None:
        self._provider_errors[provider_name] = (
            self._provider_errors.get(provider_name, 0) + 1
        )

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

    async def _update_progress(
        self, result: ScrapedResult, row: dict[str, Any],
    ) -> None:
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
            self._progress_last_rom = row.get("normalized_name", "")
            self._progress_last_provider = result.chosen_provider or "—"
            self._progress.update(1)  # type: ignore[attr-defined]
            self._progress.set_postfix(  # type: ignore[attr-defined]
                matched=self._progress_matched,
                no_match=self._progress_no_match,
                errors=self._progress_errors,
                last=f"{self._progress_last_rom} [{self._progress_last_provider}]",
            )

    async def close(self) -> None:
        """Clean up resources."""
        await self._csv_writer.close()

    @property
    def provider_errors(self) -> dict[str, int]:
        """Count of cascade errors per provider (for run summary)."""
        return dict(self._provider_errors)

    @property
    def aborted_reason(self) -> str:
        """Non-empty if the run was aborted by ``AllProvidersBlocked``."""
        return self._aborted_reason
