"""Tests for Local override/fallback provider (offline, queries DB)."""

import json
from datetime import UTC, datetime

import pytest

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.base import Provider
from multiscraper.providers.local import LocalProvider


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="ck-1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


@pytest.fixture
async def populated_db(tmp_path):
    db_path = tmp_path / "test.db"
    from multiscraper.output.db import Database
    db = Database(str(db_path))
    await db.init()
    now = datetime.now(tz=UTC).isoformat()
    media_paths = json.dumps({
        "image": "/srv/media/snes/foo.png",
        "logo": "/srv/media/snes/foo.svg",
    })
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
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_local_search_returns_candidate_from_override(populated_db):
    provider = LocalProvider(populated_db)
    await provider.setup({})

    candidates = await provider.search(_make_rom())

    assert len(candidates) == 1
    c = candidates[0]
    assert c.provider == "local"
    assert c.name == "Manual Title"
    assert c.description == "Manual description"
    assert c.match_score == 1.0
    types = sorted(ref.type for ref in c.media)
    assert types == [MediaType.IMAGE, MediaType.LOGO]

    await provider.close()


@pytest.mark.asyncio
async def test_local_search_empty_when_no_override(tmp_path):
    db_path = tmp_path / "test.db"
    from multiscraper.output.db import Database
    db = Database(str(db_path))
    await db.init()

    provider = LocalProvider(db)
    await provider.setup({})

    candidates = await provider.search(_make_rom())

    assert candidates == []
    assert isinstance(provider, Provider)
    assert provider.is_offline is True

    await provider.close()
    await db.close()


@pytest.mark.asyncio
async def test_local_fetch_media_returns_refs(populated_db):
    provider = LocalProvider(populated_db)
    await provider.setup({})

    candidates = await provider.search(_make_rom())
    media = await provider.fetch_media(candidates[0], {MediaType.IMAGE, MediaType.LOGO})

    assert MediaType.IMAGE in media
    assert MediaType.LOGO in media
    assert "foo.png" in str(media[MediaType.IMAGE].url)

    await provider.close()
