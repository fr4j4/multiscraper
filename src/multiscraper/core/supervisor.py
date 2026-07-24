"""Supervisor: worker failure recovery and dead letter queue."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class Supervisor:
    """Tracks per-worker failures and decides quarantine vs continue.

    With the DB-backed discovery model, jobs live in discovered_roms
    rather than an in-memory queue. The orchestrator calls
    `record_failure` to count failures; quarantined workers stop being
    scheduled. For backward compatibility, `report_failure` still
    implements the old in-memory requeue/DLQ flow against a queue of
    Job objects.
    """

    def __init__(
        self,
        queue: asyncio.Queue[object],
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
        self.dlq: list[object] = []

    async def record_failure(self, worker_id: str) -> bool:
        """Record one failure for worker_id. Return True if quarantined."""
        now = datetime.now(tz=UTC)
        self._failures[worker_id].append(now)

        recent = [
            t for t in self._failures[worker_id]
            if (now - t).total_seconds() < self._failure_window_sec
        ]
        if len(recent) >= self._failure_threshold:
            self._failures[worker_id] = recent
            return True
        return False

    async def report_failure(
        self, worker_id: str, job: object, error: BaseException,
    ) -> None:
        """Backward-compatible in-memory requeue/DLQ.

        The current orchestrator does not use this; the DB-backed
        path uses record_failure. Kept for tests and for the legacy
        queue path.
        """
        now = datetime.now(tz=UTC)
        self._failures[worker_id].append(now)

        recent = [
            t for t in self._failures[worker_id]
            if (now - t).total_seconds() < self._failure_window_sec
        ]
        if len(recent) >= self._failure_threshold:
            logger.error("worker_quarantined worker=%s", worker_id)
            self.dlq.append(job)
            return

        job.attempts += 1  # type: ignore[attr-defined]
        if job.attempts >= self._max_attempts:  # type: ignore[attr-defined]
            logger.warning(
                "job_to_dlq job=%s attempts=%d",
                job.job_id,  # type: ignore[attr-defined]
                job.attempts,  # type: ignore[attr-defined]
            )
            self.dlq.append(job)
        else:
            delay = self._backoff_base ** job.attempts  # type: ignore[attr-defined]
            logger.info(
                "job_requeued job=%s attempt=%d delay=%.1f",
                job.job_id,  # type: ignore[attr-defined]
                job.attempts,  # type: ignore[attr-defined]
                delay,
            )
            await asyncio.sleep(delay)
            await self._queue.put(job)
