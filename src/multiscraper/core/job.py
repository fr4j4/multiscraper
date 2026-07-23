"""Job models for the orchestrator."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from multiscraper.models import Rom, ScrapedResult


class JobState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkerPhase(StrEnum):
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
