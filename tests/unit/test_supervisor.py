"""Tests for supervisor (worker recovery + DLQ)."""

import asyncio

import pytest

from multiscraper.core.job import Job
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
    assert queue.empty()
    assert len(sup.dlq) == 1


@pytest.mark.asyncio
async def test_supervisor_quarantines_worker_after_3_failures():
    queue: asyncio.Queue[Job] = asyncio.Queue()
    sup = Supervisor(queue=queue, max_attempts=10, backoff_base=0.01,
                     failure_window_sec=60, failure_threshold=3)
    job = _make_job()
    await sup.report_failure("W-01", job, ValueError("err1"))
    await sup.report_failure("W-01", job, ValueError("err2"))
    await sup.report_failure("W-01", job, ValueError("err3"))
    assert len(sup.dlq) >= 1
