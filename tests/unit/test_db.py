"""Tests for SQLite database layer."""

from datetime import UTC, datetime

import pytest

from multiscraper.models import (
    GameMetadata,
    IdentifyMethod,
    Rom,
    RomIdentifier,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.output.db import Database


@pytest.fixture
async def db(tmp_path):
    """Create a fresh in-memory-ish database for each test."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_db_init_creates_tables(db: Database):
    """Init should create all tables without error."""
    # If we got here, init succeeded
    tables = await db.list_tables()
    assert "runs" in tables
    assert "roms" in tables
    assert "scrape_results" in tables
    assert "media" in tables
    assert "run_jobs" in tables
    assert "provider_state" in tables
    assert "source_overrides" in tables
    assert "text_provenance" in tables


@pytest.mark.asyncio
async def test_create_and_get_run(db: Database):
    run_id = await db.create_run(
        config_json={"workers": 8},
    )
    assert run_id is not None
    run = await db.get_run(run_id)
    assert run is not None
    assert run["status"] == "running"


@pytest.mark.asyncio
async def test_insert_and_get_rom(db: Database):
    rom_id = await db.insert_rom(
        system="snes",
        rel_path="./snes/test.smc",
        raw_name="test.smc",
        normalized_name="Test",
        size=1024,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="key123",
    )
    assert rom_id > 0

    rom = await db.get_rom_by_cache_key("key123")
    assert rom is not None
    assert rom["system"] == "snes"
    assert rom["crc32"] == "ab12cd34"


@pytest.mark.asyncio
async def test_insert_and_get_scrape_result(db: Database):
    run_id = await db.create_run(config_json={})
    rom_id = await db.insert_rom(
        system="snes",
        rel_path="./snes/test.smc",
        raw_name="test.smc",
        normalized_name="Test",
        size=1024,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="key123",
    )
    ri = RomIdentifier(
        rel_path="./snes/test.smc",
        size=1024,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="key123",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.OK,
        identify_method=IdentifyMethod.CRC32,
        chosen_provider="screenscraper",
        match_score=0.95,
        metadata=GameMetadata(name="Test Game"),
        fetched_at=datetime.now(tz=UTC),
    )
    await db.insert_scrape_result(run_id, rom_id, result)

    cached = await db.get_cached_result(rom_id)
    assert cached is not None
    assert cached["status"] == "OK"
    assert cached["chosen_provider"] == "screenscraper"


@pytest.mark.asyncio
async def test_insert_media(db: Database):
    run_id = await db.create_run(config_json={})
    rom_id = await db.insert_rom(
        system="snes",
        rel_path="./snes/test.smc",
        raw_name="test.smc",
        normalized_name="Test",
        size=1024,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="key123",
    )
    await db.insert_media(
        run_id=run_id,
        rom_id=rom_id,
        media_type="image",
        source="screenscraper",
        ext="jpg",
        local_path="snes/Test-image.jpg",
        bytes=50000,
        sha256="a" * 64,
        url="https://example.com/img.jpg",
    )
    media = await db.get_media_for_rom(rom_id)
    assert len(media) == 1
    assert media[0]["type"] == "image"
    assert media[0]["bytes"] == 50000
