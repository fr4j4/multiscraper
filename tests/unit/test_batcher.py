"""Tests for job batcher."""

from multiscraper.core.batcher import batch_jobs
from multiscraper.core.job import JobState
from multiscraper.models import Rom, RomIdentifier


def _make_roms(n: int, system: str = "snes") -> list[Rom]:
    roms = []
    for i in range(n):
        ri = RomIdentifier(
            rel_path=f"./{system}/game{i}.smc", size=1024, mtime=1700000000,
            crc32=f"crc{i:08x}", cache_key=f"key{i}",
        )
        roms.append(
            Rom(
                system=system,
                rom_id=ri,
                raw_name=f"game{i}.smc",
                normalized_name=f"Game {i}",
            )
        )
    return roms


def test_batch_jobs_empty() -> None:
    batches = batch_jobs([], "run1", batch_size=50)
    assert len(batches) == 0


def test_batch_jobs_single_batch() -> None:
    roms = _make_roms(10)
    batches = batch_jobs(roms, "run1", batch_size=50)
    assert len(batches) == 1
    assert len(batches[0]) == 10
    assert all(j.batch_id == 0 for j in batches[0])


def test_batch_jobs_multiple_batches() -> None:
    roms = _make_roms(120)
    batches = batch_jobs(roms, "run1", batch_size=50)
    assert len(batches) == 3
    assert len(batches[0]) == 50
    assert len(batches[1]) == 50
    assert len(batches[2]) == 20
    assert all(j.batch_id == 0 for j in batches[0])
    assert all(j.batch_id == 1 for j in batches[1])
    assert all(j.batch_id == 2 for j in batches[2])


def test_job_initial_state() -> None:
    roms = _make_roms(1)
    batches = batch_jobs(roms, "run1", batch_size=50)
    job = batches[0][0]
    assert job.state == JobState.PENDING
    assert job.attempts == 0
    assert job.worker_id is None
