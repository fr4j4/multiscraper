"""Tests for core/discovery.py: parallel discovery into discovered_roms."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
import zlib

from multiscraper.config.models import System
from multiscraper.core.discovery import (
    DiscoveryStats,
    _filter_by_extension,
    _normalize_name,
    discover_system,
)
from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.output.db import Database
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.transport.local import LocalTransport


def test_filter_by_extension_basic() -> None:
    files = ["a.gba", "b.txt", "c.GBA", "d.bin"]
    assert _filter_by_extension(files, ["gba"]) == ["a.gba", "c.GBA"]
    assert _filter_by_extension(files, ["gba", "bin"]) == ["a.gba", "c.GBA", "d.bin"]
    assert _filter_by_extension(files, []) == files


def test_normalize_name() -> None:
    assert _normalize_name("game.gba") == "game"
    assert _normalize_name("noext") == "noext"
    assert _normalize_name("a.b.c") == "a.b"


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_discover_system_empty_dir(db: Database, tmp_path: Path) -> None:
    transport = LocalTransport()
    system = System(
        name="snes", full_path=str(tmp_path / "empty"), extensions=["sfc"],
    )
    (tmp_path / "empty").mkdir()
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(tmp_path / "empty"),
    )
    assert stats.listed == 0
    assert await db.count_discovered(run_id) == 0


@pytest.mark.asyncio
async def test_discover_system_filters_by_extension(
    db: Database, tmp_path: Path,
) -> None:
    transport = LocalTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "a.gba").write_bytes(b"A")
    (roms / "b.txt").write_text("nope")
    (roms / "c.sfc").write_bytes(b"C")
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), concurrency=2,
    )
    assert stats.listed == 1
    assert stats.hashed == 1
    assert await db.count_discovered(run_id, system="gba", hash_status="done") == 1


@pytest.mark.asyncio
async def test_discover_system_parallel_hashing(
    db: Database, tmp_path: Path,
) -> None:
    """Many small files should be hashed concurrently, not serially."""
    transport = LocalTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    for i in range(20):
        (roms / f"g{i:02d}.gba").write_bytes(f"ROM-{i}".encode())
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    import time
    t0 = time.time()
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), concurrency=8,
    )
    elapsed = time.time() - t0
    assert stats.listed == 20
    assert stats.hashed == 20
    assert elapsed < 5.0, f"discovery took {elapsed:.2f}s, expected < 5s"


@pytest.mark.asyncio
async def test_discover_system_respects_limit(
    db: Database, tmp_path: Path,
) -> None:
    transport = LocalTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    for i in range(5):
        (roms / f"g{i}.gba").write_bytes(f"ROM-{i}".encode())
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), limit=2,
    )
    assert stats.listed == 2
    assert await db.count_discovered(run_id) == 2


@pytest.mark.asyncio
async def test_discover_system_handles_missing_path(
    db: Database, tmp_path: Path,
) -> None:
    transport = LocalTransport()
    system = System(
        name="gba", full_path=str(tmp_path / "missing"), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(tmp_path / "missing"),
    )
    assert stats.listed == 0
    assert await db.count_discovered(run_id) == 0


@pytest.mark.asyncio
async def test_discover_system_populates_crc32(
    db: Database, tmp_path: Path,
) -> None:
    transport = LocalTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    content = b"ROM-CONTENT-1234"
    (roms / "a.gba").write_bytes(content)
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), hash_algo="crc32",
    )
    assert stats.hashed == 1
    row = await db.claim_one_discovered(run_id, "gba")
    assert row is not None
    expected = f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"
    assert row["crc32"] == expected
    assert row["cache_key"] == f"gba:a.gba:{expected}"


@pytest.mark.asyncio
async def test_discover_system_handles_hash_failure(
    db: Database, tmp_path: Path,
) -> None:
    """A file that disappears between list_dir and hash should be marked failed."""
    class FlakyTransport(LocalTransport):
        call_count: ClassVar[int] = 0

        async def hash(self, path: str, algo: str) -> str:  # type: ignore[override]
            FlakyTransport.call_count += 1
            if FlakyTransport.call_count == 1:
                raise OSError("simulated hash failure")
            return await super().hash(path, algo)

    FlakyTransport.call_count = 0
    transport = FlakyTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "a.gba").write_bytes(b"A")
    (roms / "b.gba").write_bytes(b"B")
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), concurrency=2,
    )
    assert stats.listed == 2
    assert stats.hashed == 1
    assert stats.hash_failed == 1
    failed = await db.count_discovered(run_id, hash_status="failed")
    done = await db.count_discovered(run_id, hash_status="done")
    assert failed == 1
    assert done == 1


@pytest.mark.asyncio
async def test_discover_system_respects_concurrency_limit(
    db: Database, tmp_path: Path,
) -> None:
    """With concurrency=2, no more than 2 hashes should overlap."""
    in_flight = 0
    peak = 0

    class TrackingTransport(LocalTransport):
        async def hash(self, path: str, algo: str) -> str:  # type: ignore[override]
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.05)
                return await super().hash(path, algo)
            finally:
                in_flight -= 1

    transport = TrackingTransport()
    roms = tmp_path / "roms"
    roms.mkdir()
    for i in range(6):
        (roms / f"g{i}.gba").write_bytes(f"ROM-{i}".encode())
    system = System(
        name="gba", full_path=str(roms), extensions=["gba"],
    )
    run_id = await db.create_run(config_json={})
    await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms), concurrency=2,
    )
    assert peak <= 2
    assert peak >= 1  # we did parallelize, not serial


class _HashCallCounter(LocalTransport):
    """Local transport that records whether hash() was called."""

    hash_called: ClassVar[int] = 0

    async def hash(self, path: str, algo: str) -> str:  # type: ignore[override]
        _HashCallCounter.hash_called += 1
        return await super().hash(path, algo)


async def _seed_rom(
    db: Database, *, system: str, rel_path: str, size: int, mtime: int,
    crc32: str | None, cache_key: str, scraped: bool = True,
) -> int:
    """Insert a rom and optionally a scrape_result to anchor last_scrape_at."""
    rom_id = await db.insert_rom(
        system=system, rel_path=rel_path, raw_name=rel_path,
        normalized_name=rel_path.rsplit(".", 1)[0],
        size=size, mtime=mtime, crc32=crc32, cache_key=cache_key,
    )
    if scraped:
        from multiscraper.models import (
            IdentifyMethod, ScrapeStatus,
        )
        from multiscraper.models import ScrapedResult, Rom, RomIdentifier
        run_id = await db.create_run(config_json={})
        ri = RomIdentifier(
            rel_path=rel_path, size=size, mtime=mtime,
            crc32=crc32, cache_key=cache_key,
        )
        rom = Rom(
            system=system, rom_id=ri, raw_name=rel_path,
            normalized_name=rel_path.rsplit(".", 1)[0],
        )
        await db.insert_scrape_result(
            run_id, rom_id,
            ScrapedResult(
                rom=rom, status=ScrapeStatus.OK,
                identify_method=IdentifyMethod.CRC32,
                chosen_provider="fake", match_score=0.95,
                fetched_at=datetime.now(tz=UTC),
            ),
        )
    return rom_id


@pytest.mark.asyncio
async def test_discover_skips_hash_for_unchanged_file(
    db: Database, tmp_path: Path,
) -> None:
    """File with same size + mtime + crc32 + recent scrape: no hash call."""
    roms = tmp_path / "roms"
    roms.mkdir()
    content = b"ROM-CONTENT-1234"
    file_path = roms / "game.gba"
    file_path.write_bytes(content)
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)
    crc = f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"

    await _seed_rom(
        db, system="gba", rel_path="game.gba",
        size=size, mtime=mtime, crc32=crc,
        cache_key=f"gba:game.gba:{crc}",
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
    )
    assert _HashCallCounter.hash_called == 0
    assert stats.skipped_hash == 1
    assert stats.hashed == 0

    done = await db.count_discovered(run_id, hash_status="done")
    assert done == 1
    row = await db.claim_one_discovered(run_id, "gba")
    assert row is not None
    assert row["crc32"] == crc
    assert row["cache_key"] == f"gba:game.gba:{crc}"


@pytest.mark.asyncio
async def test_discover_rehashes_when_size_changes(
    db: Database, tmp_path: Path,
) -> None:
    """File with different size from the cached entry: must re-hash."""
    roms = tmp_path / "roms"
    roms.mkdir()
    file_path = roms / "game.gba"
    file_path.write_bytes(b"new contents longer than before")
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)

    await _seed_rom(
        db, system="gba", rel_path="game.gba",
        size=size - 10, mtime=mtime,
        crc32="00000000", cache_key="gba:game.gba:00000000",
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
    )
    assert _HashCallCounter.hash_called == 1
    assert stats.hashed == 1
    assert stats.skipped_hash == 0


@pytest.mark.asyncio
async def test_discover_rehashes_when_mtime_changes(
    db: Database, tmp_path: Path,
) -> None:
    """File with different mtime: must re-hash even if size matches."""
    roms = tmp_path / "roms"
    roms.mkdir()
    file_path = roms / "game.gba"
    file_path.write_bytes(b"X" * 100)
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)

    await _seed_rom(
        db, system="gba", rel_path="game.gba",
        size=size, mtime=mtime - 1,
        crc32="deadbeef", cache_key="gba:game.gba:deadbeef",
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
    )
    assert _HashCallCounter.hash_called == 1
    assert stats.skipped_hash == 0


@pytest.mark.asyncio
async def test_discover_rehashes_when_crc32_is_null(
    db: Database, tmp_path: Path,
) -> None:
    """Rom with crc32=NULL (hash failed previously): always re-hash."""
    roms = tmp_path / "roms"
    roms.mkdir()
    file_path = roms / "game.gba"
    file_path.write_bytes(b"recovered")
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)

    await _seed_rom(
        db, system="gba", rel_path="game.gba",
        size=size, mtime=mtime, crc32=None,
        cache_key="gba:game.gba:failed",
        scraped=False,
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
    )
    assert _HashCallCounter.hash_called == 1
    assert stats.skipped_hash == 0


@pytest.mark.asyncio
async def test_discover_rehashes_when_mtime_older_than_last_scrape(
    db: Database, tmp_path: Path,
) -> None:
    """mtime older than last_scrape_at (cp -p case): re-hash to be safe."""
    from multiscraper.models import (
        IdentifyMethod, Rom, RomIdentifier, ScrapedResult, ScrapeStatus,
    )
    roms = tmp_path / "roms"
    roms.mkdir()
    file_path = roms / "game.gba"
    file_path.write_bytes(b"X" * 100)
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)

    # Seed a rom with a mtime that's NEWER than the file's mtime, and
    # an old last_scrape_at. This simulates cp -p from a source whose
    # mtime is preserved but the source was scraped recently.
    old_scrape_at = "2020-01-01T00:00:00+00:00"
    old_run_id = await db.create_run(config_json={})
    rom_id = await db.insert_rom(
        system="gba", rel_path="game.gba", raw_name="game.gba",
        normalized_name="game", size=size, mtime=mtime + 1,
        crc32="abc", cache_key="gba:game.gba:abc",
    )
    ri = RomIdentifier(
        rel_path="game.gba", size=size, mtime=mtime + 1,
        crc32="abc", cache_key="gba:game.gba:abc",
    )
    rom = Rom(
        system="gba", rom_id=ri, raw_name="game.gba", normalized_name="game",
    )
    await db.insert_scrape_result(
        old_run_id, rom_id,
        ScrapedResult(
            rom=rom, status=ScrapeStatus.OK,
            identify_method=IdentifyMethod.CRC32,
            chosen_provider="fake", match_score=0.95,
            fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
        ),
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
    )
    assert _HashCallCounter.hash_called == 1
    assert stats.skipped_hash == 0


@pytest.mark.asyncio
async def test_discover_force_rescrape_bypasses_skip(
    db: Database, tmp_path: Path,
) -> None:
    """With force_rescrape=True, even unchanged files get re-hashed."""
    roms = tmp_path / "roms"
    roms.mkdir()
    file_path = roms / "game.gba"
    file_path.write_bytes(b"unchanged content")
    size = file_path.stat().st_size
    mtime = int(file_path.stat().st_mtime)
    crc = f"{zlib.crc32(b'unchanged content') & 0xFFFFFFFF:08x}"

    await _seed_rom(
        db, system="gba", rel_path="game.gba",
        size=size, mtime=mtime, crc32=crc,
        cache_key=f"gba:game.gba:{crc}",
    )

    _HashCallCounter.hash_called = 0
    transport = _HashCallCounter()
    system = System(name="gba", full_path=str(roms), extensions=["gba"])
    run_id = await db.create_run(config_json={})
    stats = await discover_system(
        db=db, transport=transport, run_id=run_id,
        system=system, system_path=str(roms),
        force_rescrape=True,
    )
    assert _HashCallCounter.hash_called == 1
    assert stats.hashed == 1
    assert stats.skipped_hash == 0
