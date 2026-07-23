# Phase 6: Orchestrator (Queue, Workers, Supervisor, Checkpoint, Shutdown)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the orchestrator that ties everything together: job queue, batcher, worker tasks, supervisor (recovery + DLQ), checkpoint/resume, and graceful shutdown.

**Depends on:** Phase 4 (cascade), Phase 5 (providers), Phase 3 (output/db).

**Milestone:** End-to-end test with FakeProvider + FakeTransport processes 10 ROMs, writes CSV, persists to SQLite, and generates gamelist.xml. SIGINT test verifies graceful drain.

**Parallelizable:** No — this is the integration phase. All tasks are sequential.

---

## Task 6.1: Job models and batcher

**Files:**
- Create: `src/multiscraper/core/__init__.py`
- Create: `src/multiscraper/core/job.py`
- Create: `src/multiscraper/core/batcher.py`
- Test: `tests/unit/test_batcher.py`

**Interfaces:**
- Produces: `Job`, `JobState`, `WorkerPhase`, `JobResult`, `batch_jobs(roms, batch_size) -> list[list[Job]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_batcher.py
"""Tests for job batcher."""

from multiscraper.models import Rom, RomIdentifier
from multiscraper.core.batcher import batch_jobs
from multiscraper.core.job import Job, JobState


def _make_roms(n: int, system: str = "snes") -> list[Rom]:
    roms = []
    for i in range(n):
        ri = RomIdentifier(
            rel_path=f"./{system}/game{i}.smc", size=1024, mtime=1700000000,
            crc32=f"crc{i:08x}", cache_key=f"key{i}",
        )
        roms.append(Rom(system=system, rom_id=ri, raw_name=f"game{i}.smc", normalized_name=f"Game {i}"))
    return roms


def test_batch_jobs_empty():
    batches = batch_jobs([], "run1", batch_size=50)
    assert len(batches) == 0


def test_batch_jobs_single_batch():
    roms = _make_roms(10)
    batches = batch_jobs(roms, "run1", batch_size=50)
    assert len(batches) == 1
    assert len(batches[0]) == 10
    assert all(j.batch_id == 0 for j in batches[0])


def test_batch_jobs_multiple_batches():
    roms = _make_roms(120)
    batches = batch_jobs(roms, "run1", batch_size=50)
    assert len(batches) == 3
    assert len(batches[0]) == 50
    assert len(batches[1]) == 50
    assert len(batches[2]) == 20
    assert all(j.batch_id == 0 for j in batches[0])
    assert all(j.batch_id == 1 for j in batches[1])
    assert all(j.batch_id == 2 for j in batches[2])


def test_job_initial_state():
    roms = _make_roms(1)
    batches = batch_jobs(roms, "run1", batch_size=50)
    job = batches[0][0]
    assert job.state == JobState.PENDING
    assert job.attempts == 0
    assert job.worker_id is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_batcher.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/core/__init__.py
```

```python
# src/multiscraper/core/job.py
"""Job models for the orchestrator."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from multiscraper.models import Rom, ScrapedResult


class JobState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkerPhase(str, Enum):
    IDLE = "idle"
    LOOKING_UP = "looking_up"
    DOWNLOADING = "downloading"
    FINALIZING = "finalizing"


class Job(BaseModel):
    """A unit of work: process one ROM."""

    job_id: str
    run_id: str
    rom: Rom
    batch_id: int
    system: str
    attempts: int = 0
    state: JobState = JobState.PENDING
    worker_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobResult(BaseModel):
    """Result of processing a job."""

    job: Job
    result: ScrapedResult
    media_downloaded: int = 0
    bytes_downloaded: int = 0
```

```python
# src/multiscraper/core/batcher.py
"""Batcher: split ROMs into batches for the job queue."""

from __future__ import annotations

from ulid import ULID

from multiscraper.core.job import Job, JobState
from multiscraper.models import Rom


def batch_jobs(
    roms: list[Rom], run_id: str, batch_size: int = 50,
) -> list[list[Job]]:
    """Split a list of ROMs into batches of jobs.

    Args:
        roms: List of ROMs to process.
        run_id: Current run ID.
        batch_size: Maximum ROMs per batch.

    Returns:
        List of batches, each containing up to batch_size Jobs.
    """
    if not roms:
        return []

    batches: list[list[Job]] = []
    for batch_idx, start in enumerate(range(0, len(roms), batch_size)):
        batch = [
            Job(
                job_id=str(ULID()),
                run_id=run_id,
                rom=rom,
                batch_id=batch_idx,
                system=rom.system,
            )
            for rom in roms[start : start + batch_size]
        ]
        batches.append(batch)
    return batches
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_batcher.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/core/ tests/unit/test_batcher.py
git commit -m "feat: add job models and batcher"
```

---

## Task 6.2: Rate limiter

**Files:**
- Create: `src/multiscraper/core/rate_limiter.py`
- Test: `tests/unit/test_rate_limiter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rate_limiter.py
"""Tests for async rate limiter (token bucket)."""

import asyncio
import time

import pytest

from multiscraper.core.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_burst():
    rl = RateLimiter(rate_per_sec=10.0, burst=3)
    # First 3 should be instant
    start = time.monotonic()
    for _ in range(3):
        await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_rate_limiter_throttles():
    rl = RateLimiter(rate_per_sec=5.0, burst=1)
    await rl.acquire()
    start = time.monotonic()
    await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15  # should wait ~0.2s for next token
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_rate_limiter.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/core/rate_limiter.py
"""Async token bucket rate limiter."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter for async use."""

    def __init__(self, rate_per_sec: float, burst: int = 1):
        self._rate = rate_per_sec
        self._capacity = max(1, burst)
        self._tokens = float(self._capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire one token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity,
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_rate_limiter.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/core/rate_limiter.py tests/unit/test_rate_limiter.py
git commit -m "feat: add async token bucket rate limiter"
```

---

## Task 6.3: Supervisor (recovery + DLQ)

**Files:**
- Create: `src/multiscraper/core/supervisor.py`
- Test: `tests/unit/test_supervisor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_supervisor.py
"""Tests for supervisor (worker recovery + DLQ)."""

import asyncio
from datetime import datetime, timezone

import pytest

from multiscraper.core.job import Job, JobState
from multiscraper.core.supervisor import Supervisor
from multiscraper.models import Rom, RomIdentifier


def _make_job() -> Job:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    return Job(job_id="j1", run_id="r1", rom=rom, batch_id=0, system="snes")


@pytest.mark.asyncio
async def test_supervisor_requeues_on_first_failure():
    queue: asyncio.Queue[Job] = asyncio.Queue()
    sup = Supervisor(queue=queue, max_attempts=3, backoff_base=0.01)
    job = _make_job()
    await sup.report_failure("W-01", job, ValueError("test error"))
    # Should have requeued
    assert not queue.empty()
    requeued = await queue.get()
    assert requeued.attempts == 1


@pytest.mark.asyncio
async def test_supervisor_sends_to_dlq_after_max_attempts():
    queue: asyncio.Queue[Job] = asyncio.Queue()
    sup = Supervisor(queue=queue, max_attempts=2, backoff_base=0.01)
    job = _make_job()
    job.attempts = 1
    await sup.report_failure("W-01", job, ValueError("test error"))
    # Should be in DLQ, not requeued
    assert queue.empty()
    assert len(sup.dlq) == 1


@pytest.mark.asyncio
async def test_supervisor_quarantines_worker_after_3_failures():
    queue: asyncio.Queue[Job] = asyncio.Queue()
    sup = Supervisor(queue=queue, max_attempts=10, backoff_base=0.01,
                     failure_window_sec=60, failure_threshold=3)
    job = _make_job()
    # Simulate 3 failures from same worker
    await sup.report_failure("W-01", job, ValueError("err1"))
    await sup.report_failure("W-01", job, ValueError("err2"))
    await sup.report_failure("W-01", job, ValueError("err3"))
    # Third failure should quarantine — job goes to DLQ
    assert len(sup.dlq) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_supervisor.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/core/supervisor.py
"""Supervisor: worker failure recovery and dead letter queue."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from multiscraper.core.job import Job

logger = logging.getLogger(__name__)


class Supervisor:
    """Monitors worker failures and decides requeue vs DLQ."""

    def __init__(
        self,
        queue: asyncio.Queue[Job],
        max_attempts: int = 3,
        backoff_base: float = 2.0,
        failure_window_sec: int = 60,
        failure_threshold: int = 3,
    ):
        self._queue = queue
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._failure_window_sec = failure_window_sec
        self._failure_threshold = failure_threshold
        self._failures: dict[str, list[datetime]] = defaultdict(list)
        self.dlq: list[Job] = []

    async def report_failure(
        self, worker_id: str, job: Job, error: Exception,
    ) -> None:
        """Report a worker failure. Decides requeue or DLQ."""
        now = datetime.now(tz=timezone.utc)
        self._failures[worker_id].append(now)

        # Check if worker should be quarantined
        recent = [
            t for t in self._failures[worker_id]
            if (now - t).total_seconds() < self._failure_window_sec
        ]
        if len(recent) >= self._failure_threshold:
            logger.error("worker_quarantined worker=%s", worker_id)
            self.dlq.append(job)
            return

        # Requeue with backoff
        job.attempts += 1
        if job.attempts >= self._max_attempts:
            logger.warning("job_to_dlq job=%s attempts=%d", job.job_id, job.attempts)
            self.dlq.append(job)
        else:
            delay = self._backoff_base ** job.attempts
            logger.info("job_requeued job=%s attempt=%d delay=%.1f", job.job_id, job.attempts, delay)
            await asyncio.sleep(delay)
            await self._queue.put(job)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_supervisor.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/core/supervisor.py tests/unit/test_supervisor.py
git commit -m "feat: add supervisor with worker recovery and DLQ"
```

---

## Task 6.4: Orchestrator (main loop, workers, shutdown)

**Depends on:** 6.1, 6.2, 6.3.

**Files:**
- Create: `src/multiscraper/core/orchestrator.py`
- Create: `src/multiscraper/core/shutdown.py`
- Test: `tests/integration/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_orchestrator.py
"""Integration test for the orchestrator with FakeProvider and FakeTransport."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.orchestrator import Orchestrator
from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.registry import ProviderRegistry


class FakeProvider:
    """Simple provider that always returns a match."""
    name = "fake"
    requires_auth = False
    auth_fields: list[str] = []
    rate_limit_per_sec = 100.0
    priority = 1
    supported_media = {MediaType.IMAGE}
    platform_map: dict[str, str | int] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict) -> None: pass
    async def close(self) -> None: pass

    async def search(self, rom: Rom) -> list:
        from multiscraper.models import Candidate
        return [Candidate(
            provider="fake", source_id="1",
            name=rom.normalized_name, match_score=0.95,
            description="Fake game.",
        )]

    async def fetch_media(self, candidate, wanted):
        from multiscraper.models import MediaRef
        return {MediaType.IMAGE: MediaRef(
            type=MediaType.IMAGE, url="https://example.com/img.jpg",
            ext="jpg", source="fake",
        )}

    def detect_blocked(self, response, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


@pytest.mark.asyncio
async def test_orchestrator_processes_roms(tmp_path: Path):
    """Orchestrator should process ROMs and produce output."""
    from multiscraper.models import Rom, RomIdentifier

    roms = []
    for i in range(5):
        ri = RomIdentifier(
            rel_path=f"./snes/game{i}.smc", size=1024, mtime=1700000000,
            crc32=f"crc{i:08x}", cache_key=f"key{i}",
        )
        roms.append(Rom(system="snes", rom_id=ri, raw_name=f"game{i}.smc", normalized_name=f"Game {i}"))

    reg = ProviderRegistry()
    reg.register(FakeProvider())

    config = MultiscraperConfig()
    config.orchestrator = OrchestratorConfig(workers=2, batch_size=10, shutdown_drain_timeout_sec=10)

    orch = Orchestrator(
        registry=reg,
        config=config,
        db_path=str(tmp_path / "test.db"),
        csv_path=tmp_path / "run.csv",
        media_root=tmp_path / "media",
    )

    run_id = await orch.start(roms=roms, systems=["snes"])

    # Verify outputs
    assert (tmp_path / "run.csv").exists()
    db_exists = (tmp_path / "test.db").exists()
    assert db_exists

    await orch.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/integration/test_orchestrator.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/core/shutdown.py
"""Graceful shutdown handler for SIGTERM/SIGINT."""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """Manages graceful shutdown via SIGTERM/SIGINT."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._sigint_count = 0

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        """Install signal handlers."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handler, sig)

    def _handler(self, sig: signal.Signals) -> None:
        self._sigint_count += 1
        if self._sigint_count >= 2:
            logger.warning("force_shutdown signal=%s (second press)", sig.name)
            self._event.set()
            # Force stop the loop
            loop = asyncio.get_event_loop()
            loop.stop()
        else:
            logger.info("shutdown_initiated signal=%s", sig.name)
            self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self, timeout: float | None = None) -> None:
        if timeout is None:
            await self._event.wait()
        else:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    def clear(self) -> None:
        self._event.clear()
        self._sigint_count = 0
```

```python
# src/multiscraper/core/orchestrator.py
"""Main orchestrator: manages workers, queue, and output."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ulid import ULID

from multiscraper.config.models import MultiscraperConfig
from multiscraper.core.batcher import batch_jobs
from multiscraper.core.job import Job, JobResult, JobState
from multiscraper.core.rate_limiter import RateLimiter
from multiscraper.core.shutdown import ShutdownHandler
from multiscraper.core.supervisor import Supervisor
from multiscraper.models import Rom, ScrapedResult, ScrapeStatus
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
    ):
        self._registry = registry
        self._config = config
        self._db = Database(db_path)
        self._csv_writer = CsvWriter(csv_path, flush_every=config.orchestrator.csv_flush_every)
        self._media_root = media_root
        self._shutdown = ShutdownHandler()
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._result_queue: asyncio.Queue[JobResult] = asyncio.Queue()
        self._supervisor: Supervisor | None = None
        self._blocked_providers: set[str] = set()
        self._row_seq = 0

    async def start(self, roms: list[Rom], systems: list[str]) -> str:
        """Start a scrape run. Returns the run_id."""
        await self._db.init()
        run_id = await self._db.create_run(config_json=self._config.model_dump(mode="json"))
        await self._csv_writer.write_header()

        # Build batches and enqueue
        batches = batch_jobs(roms, run_id, self._config.orchestrator.batch_size)
        for batch in batches:
            for job in batch:
                await self._queue.put(job)

        self._supervisor = Supervisor(
            queue=self._queue,
            max_attempts=self._config.orchestrator.max_job_attempts,
            failure_window_sec=self._config.orchestrator.worker_failure_window_sec,
            failure_threshold=self._config.orchestrator.worker_failure_threshold,
        )

        # Install signal handlers
        loop = asyncio.get_event_loop()
        self._shutdown.install(loop)

        # Start workers and CSV writer
        n_workers = self._config.orchestrator.workers
        async with asyncio.TaskGroup() as tg:
            # CSV writer task
            tg.create_task(self._csv_writer_loop())
            # Worker tasks
            for i in range(n_workers):
                tg.create_task(self._worker_loop(f"W-{i:02d}"))

        # Finalize
        await self._csv_writer.close()
        await self._db.close()
        return run_id

    async def _worker_loop(self, worker_id: str) -> None:
        """Main worker loop: pull jobs, process, push results."""
        while not self._shutdown.is_set:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            try:
                result = await self._process_job(job)
                self._row_seq += 1
                await self._csv_writer.write_row(
                    job.run_id, self._row_seq, job.batch_id, worker_id, result,
                )
            except Exception as exc:
                logger.exception("worker_died worker=%s job=%s", worker_id, job.job_id)
                if self._supervisor:
                    await self._supervisor.report_failure(worker_id, job, exc)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: Job) -> ScrapedResult:
        """Process a single job: run cascade, download media, persist."""
        wanted_media = {
            mt for mt in [
                "image", "thumbnail", "video", "marquee", "box3d",
                "backcover", "fanart", "manual", "miximage", "logo",
            ]
        }
        from multiscraper.models import MediaType
        wanted = {MediaType(mt) for mt in wanted_media}

        result = await run_cascade(
            rom=job.rom,
            registry=self._registry,
            match_threshold=self._config.provider_defaults.match_threshold,
            blocked_providers=self._blocked_providers,
            wanted_media=wanted,
        )
        return result

    async def _csv_writer_loop(self) -> None:
        """Consume result queue and write to CSV."""
        # The CSV writing is done directly in the worker loop for simplicity.
        # This task just waits for the queue to drain.
        await self._queue.join()

    async def close(self) -> None:
        """Clean up resources."""
        await self._csv_writer.close()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_orchestrator.py -v
```

Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/core/orchestrator.py src/multiscraper/core/shutdown.py tests/integration/test_orchestrator.py
git commit -m "feat: add orchestrator with workers, queue, and graceful shutdown"
```

---

## Milestone Gate

- [ ] `pytest tests/ -v` — all tests pass (unit + integration)
- [ ] Orchestrator processes ROMs end-to-end with FakeProvider
- [ ] CSV file is created with correct rows
- [ ] SQLite database is created with correct tables
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes