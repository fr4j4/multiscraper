"""Tests for summary.json and log JSONL writers."""

import json
from datetime import UTC, datetime
from pathlib import Path

from multiscraper.models import RunReport
from multiscraper.output.log_jsonl import JsonlLogWriter
from multiscraper.output.summary import write_summary


def test_write_summary_creates_valid_json(tmp_path: Path):
    report = RunReport(
        run_id="01HTEST",
        started_at=datetime.now(tz=UTC),
        config_snapshot={"workers": 8},
    )
    report.totals.roms_total = 100
    report.totals.roms_ok = 90
    report.totals.roms_no_match = 10

    summary_path = tmp_path / "summary.json"
    write_summary(report, summary_path)

    data = json.loads(summary_path.read_text())
    assert data["run_id"] == "01HTEST"
    assert data["totals"]["roms_total"] == 100
    assert data["totals"]["roms_ok"] == 90
    assert data["status"] == "running"


def test_jsonl_log_writer_writes_events(tmp_path: Path):
    log_path = tmp_path / "run.log.jsonl"
    writer = JsonlLogWriter(log_path)
    writer.log_event("run_start", level="INFO", run_id="01HTEST", systems=["snes"])
    writer.log_event("rom_done", level="INFO", rom="./snes/test.smc", status="OK")
    writer.close()

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    evt1 = json.loads(lines[0])
    assert evt1["event"] == "run_start"
    assert evt1["level"] == "INFO"
    assert evt1["run_id"] == "01HTEST"
    evt2 = json.loads(lines[1])
    assert evt2["event"] == "rom_done"
    assert evt2["status"] == "OK"
