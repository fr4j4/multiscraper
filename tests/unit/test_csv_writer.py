"""Tests for CSV writer."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from multiscraper.models import (
    GameMetadata,
    IdentifyMethod,
    MediaFile,
    MediaType,
    Rom,
    RomIdentifier,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.output.csv_writer import CSV_COLUMNS, CsvWriter


def _make_result(status=ScrapeStatus.OK, media=None) -> ScrapedResult:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    return ScrapedResult(
        rom=rom,
        status=status,
        identify_method=IdentifyMethod.CRC32,
        chosen_provider="screenscraper",
        match_score=0.95,
        metadata=GameMetadata(name="Test Game"),
        media=media or [],
        fetched_at=datetime.now(tz=UTC),
        elapsed_ms=1234,
    )


@pytest.mark.asyncio
async def test_csv_writer_creates_file_with_header(tmp_path: Path):
    csv_path = tmp_path / "run.csv"
    writer = CsvWriter(csv_path)
    await writer.write_header()
    await writer.close()

    content = csv_path.read_text()
    header_line = content.splitlines()[0]
    assert "run_id" in header_line
    assert "rom_relpath" in header_line
    assert "image" in header_line
    assert "video" in header_line


@pytest.mark.asyncio
async def test_csv_writer_writes_ok_row(tmp_path: Path):
    csv_path = tmp_path / "run.csv"
    writer = CsvWriter(csv_path)
    await writer.write_header()

    result = _make_result(
        media=[
            MediaFile(type=MediaType.IMAGE, local_path="snes/Test-image.jpg",
                      ext="jpg", bytes=50000, sha256="a"*64, source="screenscraper"),
        ]
    )
    await writer.write_row("01HTEST", 1, 0, "W-01", result)
    await writer.close()

    content = csv_path.read_text()
    lines = content.strip().splitlines()
    assert len(lines) == 2  # header + 1 row
    row = lines[1]
    assert "01HTEST" in row
    assert "snes" in row
    assert "OK" in row
    assert "screenscraper" in row


@pytest.mark.asyncio
async def test_csv_writer_writes_no_match_row(tmp_path: Path):
    csv_path = tmp_path / "run.csv"
    writer = CsvWriter(csv_path)
    await writer.write_header()

    result = _make_result(status=ScrapeStatus.NO_MATCH)
    result.chosen_provider = None
    result.match_score = None
    result.metadata = None
    await writer.write_row("01HTEST", 1, 0, "W-01", result)
    await writer.close()

    content = csv_path.read_text()
    lines = content.strip().splitlines()
    row = lines[1]
    assert "NO_MATCH" in row


def test_csv_columns_count():
    assert len(CSV_COLUMNS) > 30
    assert "run_id" in CSV_COLUMNS
    assert "name_language" in CSV_COLUMNS
    assert "desc_language" in CSV_COLUMNS
    assert "logo" in CSV_COLUMNS
