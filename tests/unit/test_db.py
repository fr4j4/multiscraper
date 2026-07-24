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


@pytest.mark.asyncio
async def test_get_override_by_cache_key(db: Database):
    """get_override_by_cache_key returns the row or None."""
    from datetime import UTC, datetime
    now = datetime.now(tz=UTC).isoformat()
    media_paths = '{"image": "/srv/media/snes/foo.png", "logo": "/srv/media/snes/foo.svg"}'
    assert db._conn is not None
    await db._conn.execute(
        "INSERT INTO source_overrides (cache_key, name, desc, image_path, "
        "metadata_json, media_paths_json, confidence, note, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ck-1", "Manual Title", "Manual description",
            "/srv/media/snes/foo.png", '{"genre": "Action"}',
            media_paths, 1.0, "test override", now,
        ),
    )
    await db._conn.commit()

    row = await db.get_override_by_cache_key("ck-1")
    assert row is not None
    assert row["cache_key"] == "ck-1"
    assert row["name"] == "Manual Title"
    assert row["desc"] == "Manual description"
    assert row["image_path"] == "/srv/media/snes/foo.png"
    assert row["media_paths_json"] == media_paths
    assert row["confidence"] == 1.0
    assert row["note"] == "test override"

    missing = await db.get_override_by_cache_key("does-not-exist")
    assert missing is None


@pytest.mark.asyncio
async def test_discovered_roms_table_exists(db: Database):
    """Migration 0002 should create discovered_roms."""
    tables = await db.list_tables()
    assert "discovered_roms" in tables


@pytest.mark.asyncio
async def test_truncate_discovered_roms(db: Database):
    """truncate_discovered_roms removes all rows but keeps the table."""
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 0, "mtime": 0, "cache_key": ""},
        {"rel_path": "b.smc", "raw_name": "b.smc", "normalized_name": "b",
         "size": 0, "mtime": 0, "cache_key": ""},
    ])
    assert await db.count_discovered(run_id) == 2
    await db.truncate_discovered_roms()
    assert await db.count_discovered(run_id) == 0


@pytest.mark.asyncio
async def test_insert_and_find_pending(db: Database):
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 0, "mtime": 0, "cache_key": ""},
    ])
    row_id = await db.find_pending_discovered_id(run_id, "snes", "a.smc")
    assert row_id is not None
    assert row_id > 0
    missing = await db.find_pending_discovered_id(run_id, "snes", "missing.smc")
    assert missing is None


@pytest.mark.asyncio
async def test_update_discovered_hash_marks_done(db: Database):
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 0, "mtime": 0, "cache_key": ""},
    ])
    row_id = await db.find_pending_discovered_id(run_id, "snes", "a.smc")
    assert row_id is not None
    await db.update_discovered_hash(
        row_id, size=1024, mtime=1700000000,
        crc32="ab12cd34", sha1=None,
        cache_key="snes:a.smc:ab12cd34", status="done",
    )
    pending = await db.count_discovered(run_id, hash_status="pending")
    done = await db.count_discovered(run_id, hash_status="done")
    assert pending == 0
    assert done == 1


@pytest.mark.asyncio
async def test_claim_one_discovered(db: Database):
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 100, "mtime": 1, "cache_key": ""},
        {"rel_path": "b.smc", "raw_name": "b.smc", "normalized_name": "b",
         "size": 200, "mtime": 2, "cache_key": ""},
    ])
    for f in ("a.smc", "b.smc"):
        rid = await db.find_pending_discovered_id(run_id, "snes", f)
        assert rid is not None
        await db.update_discovered_hash(
            rid, size=100, mtime=1, crc32="x", sha1=None,
            cache_key=f"snes:{f}:x", status="done",
        )
    claimed = await db.claim_one_discovered(run_id, "snes")
    assert claimed is not None
    assert claimed["hash_status"] == "claimed"
    assert claimed["rel_path"] in ("a.smc", "b.smc")
    claimed_again = await db.claim_one_discovered(run_id, "snes")
    assert claimed_again is not None
    assert claimed_again["rel_path"] != claimed["rel_path"]
    nothing = await db.claim_one_discovered(run_id, "snes")
    assert nothing is None


@pytest.mark.asyncio
async def test_release_discovered(db: Database):
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 0, "mtime": 0, "cache_key": ""},
    ])
    rid = await db.find_pending_discovered_id(run_id, "snes", "a.smc")
    assert rid is not None
    await db.update_discovered_hash(
        rid, size=0, mtime=0, crc32="x", sha1=None,
        cache_key="snes:a.smc:x", status="done",
    )
    claimed = await db.claim_one_discovered(run_id, "snes")
    assert claimed is not None
    assert claimed["hash_status"] == "claimed"
    await db.release_discovered(int(claimed["id"]), status="done")
    reclaim = await db.claim_one_discovered(run_id, "snes")
    assert reclaim is not None
    assert reclaim["id"] == claimed["id"]


@pytest.mark.asyncio
async def test_count_discovered_filters(db: Database):
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {"rel_path": "a.smc", "raw_name": "a.smc", "normalized_name": "a",
         "size": 0, "mtime": 0, "cache_key": ""},
        {"rel_path": "b.smc", "raw_name": "b.smc", "normalized_name": "b",
         "size": 0, "mtime": 0, "cache_key": ""},
    ])
    rid = await db.find_pending_discovered_id(run_id, "snes", "a.smc")
    assert rid is not None
    await db.update_discovered_hash(
        rid, size=0, mtime=0, crc32="x", sha1=None,
        cache_key="x", status="done",
    )
    assert await db.count_discovered(run_id) == 2
    assert await db.count_discovered(run_id, system="snes") == 2
    assert await db.count_discovered(run_id, system="missing") == 0
    assert await db.count_discovered(run_id, hash_status="done") == 1
    assert await db.count_discovered(run_id, hash_status="pending") == 1
