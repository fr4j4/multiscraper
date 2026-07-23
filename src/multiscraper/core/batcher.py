"""Batcher: split ROMs into batches for the job queue."""

from __future__ import annotations

from ulid import ULID

from multiscraper.core.job import Job
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
