"""Main orchestrator: manages workers, queue, and output."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.batcher import batch_jobs
from multiscraper.core.job import Job
from multiscraper.core.shutdown import ShutdownHandler
from multiscraper.core.supervisor import Supervisor
from multiscraper.models import MediaType, Rom, ScrapedResult
from multiscraper.output.csv_writer import CsvWriter
from multiscraper.output.db import Database
from multiscraper.providers.cascade import run_cascade
from multiscraper.providers.registry import ProviderRegistry

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

    async def start(self, roms: list[Rom], systems: list[str]) -> str:
        """Start a scrape run. Returns the run_id."""
        await self._db.init()
        run_id = await self._db.create_run(
            config_json=self._config.model_dump(mode="json"),
        )
        await self._csv_writer.write_header()

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

        loop = asyncio.get_event_loop()
        self._shutdown.install(loop)

        n_workers = self._orchestrator.workers
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._csv_writer_loop())
            for i in range(n_workers):
                tg.create_task(self._worker_loop(f"W-{i:02d}"))

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
            except Exception as exc:
                logger.exception(
                    "worker_died worker=%s job=%s", worker_id, job.job_id,
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
        return cascade_result.to_scraped_result()

    async def _csv_writer_loop(self) -> None:
        """Consume result queue and write to CSV."""
        await self._queue.join()

    async def close(self) -> None:
        """Clean up resources."""
        await self._csv_writer.close()
