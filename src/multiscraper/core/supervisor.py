"""Supervisor: worker failure recovery and dead letter queue."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime

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

        job.attempts += 1
        if job.attempts >= self._max_attempts:
            logger.warning("job_to_dlq job=%s attempts=%d", job.job_id, job.attempts)
            self.dlq.append(job)
        else:
            delay = self._backoff_base ** job.attempts
            logger.info(
                "job_requeued job=%s attempt=%d delay=%.1f",
                job.job_id, job.attempts, delay,
            )
            await asyncio.sleep(delay)
            await self._queue.put(job)
