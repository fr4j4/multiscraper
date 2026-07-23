# Phase 3: Output Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the output layer: SQLite database with migrations, CSV writer (streaming), gamelist.xml generator, summary.json writer, and run.log.jsonl writer.

**Depends on:** Phase 1 (models), Phase 2 (config).

**Milestone:** DB roundtrip test passes (insert + query); CSV write test passes with correct columns; XML generation test passes with valid ES format; `ruff` and `mypy` pass.

**Parallelizable:** Yes — 3 independent tracks (Task 3.1 DB, Task 3.2 CSV, Task 3.3 XML). Task 3.4 (summary + log) depends on 3.1.

---

## Task 3.1: SQLite database with migrations

**Files:**
- Create: `src/multiscraper/output/__init__.py`
- Create: `src/multiscraper/output/db.py`
- Create: `src/multiscraper/db/migrations/0001_initial.sql`
- Test: `tests/unit/test_db.py`

**Interfaces:**
- Produces: `Database` (class with async methods: `init()`, `create_run()`, `insert_rom()`, `insert_scrape_result()`, `insert_media()`, `get_cached_result()`, `mark_job_*()`, `close()`)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_db.py
"""Tests for SQLite database layer."""

import asyncio
from datetime import datetime, timezone

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
    ri = RomIdentifier(rel_path="./snes/test.smc", size=1024, mtime=1700000000, crc32="ab12cd34", cache_key="key123")
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.OK,
        identify_method=IdentifyMethod.CRC32,
        chosen_provider="screenscraper",
        match_score=0.95,
        metadata=GameMetadata(name="Test Game"),
        fetched_at=datetime.now(tz=timezone.utc),
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_db.py -v
```

Expected: FAIL

- [ ] **Step 3: Write the migration SQL**

```sql
-- src/multiscraper/db/migrations/0001_initial.sql

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL CHECK (status IN
                        ('running','ok','partial','paused','aborted','error')),
    config_json     TEXT NOT NULL,
    totals_json     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS roms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key       TEXT NOT NULL UNIQUE,
    system          TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    raw_name        TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    size            INTEGER NOT NULL,
    mtime           INTEGER NOT NULL,
    crc32           TEXT,
    sha1            TEXT,
    first_seen_run  TEXT REFERENCES runs(id) ON DELETE SET NULL,
    UNIQUE (system, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_roms_system ON roms(system);
CREATE INDEX IF NOT EXISTS idx_roms_crc32  ON roms(crc32);
CREATE INDEX IF NOT EXISTS idx_roms_sha1   ON roms(sha1);

CREATE TABLE IF NOT EXISTS scrape_results (
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    identify_method TEXT NOT NULL,
    chosen_provider TEXT,
    match_score     REAL,
    metadata_json   TEXT,
    error           TEXT,
    warnings_json   TEXT,
    elapsed_ms      INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, rom_id)
);
CREATE INDEX IF NOT EXISTS idx_results_status ON scrape_results(run_id, status);
CREATE INDEX IF NOT EXISTS idx_results_rom    ON scrape_results(rom_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS media (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    source          TEXT NOT NULL,
    ext             TEXT NOT NULL,
    local_path      TEXT NOT NULL,
    bytes           INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    url             TEXT NOT NULL,
    UNIQUE (rom_id, type)
);
CREATE INDEX IF NOT EXISTS idx_media_rom ON media(rom_id);
CREATE INDEX IF NOT EXISTS idx_media_run ON media(run_id);

CREATE TABLE IF NOT EXISTS run_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    batch_id        INTEGER NOT NULL,
    worker_id       TEXT,
    status          TEXT NOT NULL CHECK (status IN
                        ('pending','in_progress','done','failed','skipped')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    finished_at      TEXT,
    error           TEXT,
    UNIQUE (run_id, rom_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_pending ON run_jobs(run_id, status)
    WHERE status IN ('pending','in_progress');

CREATE TABLE IF NOT EXISTS provider_state (
    provider        TEXT PRIMARY KEY,
    last_call_at    TEXT,
    blocked_until   TEXT,
    last_error      TEXT,
    total_calls     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_overrides (
    cache_key        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    desc             TEXT,
    image_path       TEXT,
    metadata_json    TEXT,
    media_paths_json TEXT,
    confidence       REAL DEFAULT 1.0,
    note             TEXT,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS text_provenance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id      INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    language    TEXT,
    source      TEXT NOT NULL,
    UNIQUE (run_id, rom_id, field)
);
CREATE INDEX IF NOT EXISTS idx_text_prov_rom ON text_provenance(rom_id);
```

- [ ] **Step 4: Write the Database class**

```python
# src/multiscraper/output/__init__.py
```

```python
# src/multiscraper/output/db.py
"""SQLite database layer for multiscraper.

Uses aiosqlite for async access. WAL mode for concurrent read/write.
Migrations are applied on init from db/migrations/*.sql files.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from ulid import ULID

from multiscraper.models import ScrapedResult

_MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"


class Database:
    """Async SQLite database for multiscraper cache and run state."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open connection, enable WAL, run migrations."""
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()
        await self._conn.commit()

    async def _run_migrations(self) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        cursor = await self._conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current_version = row[0] if row and row[0] else 0
        await cursor.close()

        if not _MIGRATIONS_DIR.exists():
            return

        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = int(sql_file.stem.split("_")[0])
            if version <= current_version:
                continue
            sql = sql_file.read_text(encoding="utf-8")
            await self._conn.executescript(sql)
            await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def list_tables(self) -> list[str]:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

    async def create_run(self, config_json: dict) -> str:
        assert self._conn is not None
        run_id = str(ULID())
        now = datetime.now(tz=timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO runs (id, started_at, status, config_json) VALUES (?, ?, 'running', ?)",
            (run_id, now, json.dumps(config_json)),
        )
        await self._conn.commit()
        return run_id

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, started_at, finished_at, status, config_json, totals_json "
            "FROM runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "started_at": row[1],
            "finished_at": row[2],
            "status": row[3],
            "config_json": json.loads(row[4]),
            "totals_json": json.loads(row[5]),
        }

    async def insert_rom(
        self,
        system: str,
        rel_path: str,
        raw_name: str,
        normalized_name: str,
        size: int,
        mtime: int,
        crc32: str | None,
        cache_key: str,
        sha1: str | None = None,
    ) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "INSERT INTO roms (cache_key, system, rel_path, raw_name, normalized_name, "
            "size, mtime, crc32, sha1) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET crc32=excluded.crc32, sha1=excluded.sha1",
            (cache_key, system, rel_path, raw_name, normalized_name, size, mtime, crc32, sha1),
        )
        await self._conn.commit()
        rom_id = cursor.lastrowid
        await cursor.close()
        assert rom_id is not None
        return rom_id

    async def get_rom_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, cache_key, system, rel_path, raw_name, normalized_name, "
            "size, mtime, crc32, sha1 FROM roms WHERE cache_key = ?",
            (cache_key,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0], "cache_key": row[1], "system": row[2], "rel_path": row[3],
            "raw_name": row[4], "normalized_name": row[5], "size": row[6],
            "mtime": row[7], "crc32": row[8], "sha1": row[9],
        }

    async def insert_scrape_result(self, run_id: str, rom_id: int, result: ScrapedResult) -> None:
        assert self._conn is not None
        now = datetime.now(tz=timezone.utc).isoformat()
        metadata_json = result.metadata.model_dump_json() if result.metadata else None
        warnings_json = json.dumps(result.warnings) if result.warnings else "[]"
        await self._conn.execute(
            "INSERT INTO scrape_results (run_id, rom_id, status, identify_method, "
            "chosen_provider, match_score, metadata_json, error, warnings_json, "
            "elapsed_ms, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, rom_id) DO UPDATE SET status=excluded.status, "
            "metadata_json=excluded.metadata_json",
            (run_id, rom_id, result.status.value, result.identify_method.value,
             result.chosen_provider, result.match_score, metadata_json,
             result.error, warnings_json, result.elapsed_ms, now),
        )
        await self._conn.commit()

    async def get_cached_result(self, rom_id: int) -> dict[str, Any] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT status, chosen_provider, match_score, metadata_json, error "
            "FROM scrape_results WHERE rom_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (rom_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "status": row[0], "chosen_provider": row[1], "match_score": row[2],
            "metadata_json": json.loads(row[3]) if row[3] else None, "error": row[4],
        }

    async def insert_media(
        self, run_id: str, rom_id: int, media_type: str, source: str,
        ext: str, local_path: str, bytes_: int, sha256: str, url: str,
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO media (run_id, rom_id, type, source, ext, local_path, "
            "bytes, sha256, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(rom_id, type) DO UPDATE SET local_path=excluded.local_path, "
            "bytes=excluded.bytes, sha256=excluded.sha256",
            (run_id, rom_id, media_type, source, ext, local_path, bytes_, sha256, url),
        )
        await self._conn.commit()

    async def get_media_for_rom(self, rom_id: int) -> list[dict[str, Any]]:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT type, source, ext, local_path, bytes, sha256, url "
            "FROM media WHERE rom_id = ?",
            (rom_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"type": r[0], "source": r[1], "ext": r[2], "local_path": r[3],
             "bytes": r[4], "sha256": r[5], "url": r[6]}
            for r in rows
        ]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/unit/test_db.py -v
```

Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
mkdir -p src/multiscraper/db/migrations
git add src/multiscraper/output/ src/multiscraper/db/ tests/unit/test_db.py
git commit -m "feat: add SQLite database layer with WAL mode and migrations"
```

---

## Task 3.2: CSV writer (streaming)

**Files:**
- Create: `src/multiscraper/output/csv_writer.py`
- Test: `tests/unit/test_csv_writer.py`

**Interfaces:**
- Produces: `CsvWriter` (class with `write_row(result: JobResult)`, `flush()`, `close()`)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_csv_writer.py
"""Tests for CSV writer."""

import csv
from datetime import datetime, timezone
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
        fetched_at=datetime.now(tz=timezone.utc),
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_csv_writer.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/output/csv_writer.py
"""Streaming CSV writer for run reports.

Writes one row per ROM with all columns defined in the spec.
Flushes every N rows for performance. Append-only during a run.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import TextIO

from multiscraper.models import ScrapedResult

CSV_COLUMNS = [
    "run_id", "row_seq", "system", "batch_id", "worker_id",
    "rom_relpath", "rom_raw_name", "rom_size", "rom_crc32", "rom_sha1",
    "identify_method", "status", "match_score", "chosen_provider",
    "fetched_at", "elapsed_ms", "error", "warnings",
    "name", "name_language",
    "desc", "desc_language", "desc_source",
    "genre", "genre_language", "genre_source",
    "releasedate", "developer", "publisher",
    "players", "rating",
    "image", "thumbnail", "video", "marquee", "box3d", "backcover",
    "fanart", "manual", "miximage", "logo",
    "total_media_ok", "total_media_bytes",
]

_MEDIA_TYPES = [
    "image", "thumbnail", "video", "marquee", "box3d", "backcover",
    "fanart", "manual", "miximage", "logo",
]


class CsvWriter:
    """Streaming CSV writer for run reports."""

    def __init__(self, path: Path, flush_every: int = 50):
        self._path = path
        self._flush_every = flush_every
        self._file: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self._buffer_count = 0
        self._lock = asyncio.Lock()

    async def write_header(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=CSV_COLUMNS, lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        self._writer.writeheader()
        self._file.flush()

    async def write_row(
        self, run_id: str, row_seq: int, batch_id: int,
        worker_id: str, result: ScrapedResult,
    ) -> None:
        assert self._writer is not None
        async with self._lock:
            row = self._result_to_row(run_id, row_seq, batch_id, worker_id, result)
            self._writer.writerow(row)
            self._buffer_count += 1
            if self._buffer_count >= self._flush_every:
                assert self._file is not None
                self._file.flush()
                self._buffer_count = 0

    def _result_to_row(
        self, run_id: str, row_seq: int, batch_id: int,
        worker_id: str, result: ScrapedResult,
    ) -> dict[str, str]:
        rom = result.rom
        ri = rom.rom_id
        md = result.metadata

        media_by_type = {m.type.value: m for m in result.media}
        media_cells: dict[str, str] = {}
        total_ok = 0
        total_bytes = 0
        for mt in _MEDIA_TYPES:
            if mt in media_by_type:
                mf = media_by_type[mt]
                media_cells[mt] = f"OK:{mf.bytes}"
                total_ok += 1
                total_bytes += mf.bytes
            elif result.status.value in ("NO_MATCH", "SKIPPED", "BLOCKED"):
                media_cells[mt] = ""
            else:
                media_cells[mt] = "MISSING"

        return {
            "run_id": run_id,
            "row_seq": str(row_seq),
            "system": rom.system,
            "batch_id": str(batch_id),
            "worker_id": worker_id,
            "rom_relpath": ri.rel_path,
            "rom_raw_name": rom.raw_name,
            "rom_size": str(ri.size),
            "rom_crc32": ri.crc32 or "",
            "rom_sha1": ri.sha1 or "",
            "identify_method": result.identify_method.value,
            "status": result.status.value,
            "match_score": f"{result.match_score:.4f}" if result.match_score is not None else "",
            "chosen_provider": result.chosen_provider or "",
            "fetched_at": result.fetched_at.isoformat(),
            "elapsed_ms": str(result.elapsed_ms),
            "error": result.error or "",
            "warnings": ";".join(result.warnings) if result.warnings else "",
            "name": md.name if md else "",
            "name_language": "",
            "desc": md.desc if md and md.desc else "",
            "desc_language": "",
            "desc_source": "",
            "genre": md.genre if md and md.genre else "",
            "genre_language": "",
            "genre_source": "",
            "releasedate": md.releasedate.strftime("%Y%m%dT%H%M%S") if md and md.releasedate else "",
            "developer": md.developer if md and md.developer else "",
            "publisher": md.publisher if md and md.publisher else "",
            "players": str(md.players) if md and md.players else "",
            "rating": f"{md.rating:.2f}" if md and md.rating is not None else "",
            **media_cells,
            "total_media_ok": str(total_ok),
            "total_media_bytes": str(total_bytes),
        }

    async def flush(self) -> None:
        if self._file is not None:
            self._file.flush()
        self._buffer_count = 0

    async def close(self) -> None:
        await self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None
        self._writer = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_csv_writer.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/output/csv_writer.py tests/unit/test_csv_writer.py
git commit -m "feat: add streaming CSV writer with all spec columns"
```

---

## Task 3.3: gamelist.xml generator

**Files:**
- Create: `src/multiscraper/output/gamelist_xml.py`
- Test: `tests/unit/test_gamelist_xml.py`

**Interfaces:**
- Produces: `generate_gamelist(results: list[ScrapedResult], system: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gamelist_xml.py
"""Tests for gamelist.xml generator."""

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

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
from multiscraper.output.gamelist_xml import generate_gamelist


def _make_result(name="Test Game", status=ScrapeStatus.OK, with_media=True) -> ScrapedResult:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    media = []
    if with_media:
        media = [
            MediaFile(type=MediaType.IMAGE, local_path="snes/Test-image.jpg",
                      ext="jpg", bytes=50000, sha256="a"*64, source="screenscraper"),
            MediaFile(type=MediaType.VIDEO, local_path="snes/Test-video.mp4",
                      ext="mp4", bytes=5000000, sha256="b"*64, source="screenscraper"),
        ]
    return ScrapedResult(
        rom=rom,
        status=status,
        identify_method=IdentifyMethod.CRC32,
        chosen_provider="screenscraper",
        match_score=0.95,
        metadata=GameMetadata(
            name=name,
            desc="A test game.",
            releasedate=datetime(1990, 8, 23, tzinfo=timezone.utc),
            developer="Nintendo",
            publisher="Nintendo",
            genre="Platform",
            players=1,
            rating=0.95,
        ),
        media=media,
        fetched_at=datetime.now(tz=timezone.utc),
    )


def test_generate_gamelist_basic():
    results = [_make_result()]
    xml = generate_gamelist(results, "snes")
    root = ET.fromstring(xml)
    assert root.tag == "gameList"
    games = root.findall("game")
    assert len(games) == 1
    game = games[0]
    assert game.find("path").text == "./snes/test.smc"
    assert game.find("name").text == "Test Game"
    assert game.find("desc").text == "A test game."
    assert game.find("developer").text == "Nintendo"
    assert game.find("genre").text == "Platform"
    assert game.find("rating").text == "0.95"
    assert game.find("releasedate").text == "19900823T000000"
    assert game.find("image").text is not None
    assert game.find("video").text is not None


def test_generate_gamelist_no_match_includes_path_only():
    ri = RomIdentifier(
        rel_path="./snes/mystery.rom", size=100, mtime=1000, cache_key="k2",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="mystery.rom", normalized_name="Mystery")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.NO_MATCH,
        identify_method=IdentifyMethod.NAME_ONLY,
        fetched_at=datetime.now(tz=timezone.utc),
    )
    xml = generate_gamelist([result], "snes")
    root = ET.fromstring(xml)
    games = root.findall("game")
    assert len(games) == 1
    game = games[0]
    assert game.find("path").text == "./snes/mystery.rom"
    assert game.find("name") is None
    assert game.find("desc") is None


def test_generate_gamelist_empty_tags_omitted():
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=100, mtime=1000, cache_key="k3",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.PARTIAL,
        identify_method=IdentifyMethod.CRC32,
        metadata=GameMetadata(name="Test"),  # only name, no desc/genre/etc
        fetched_at=datetime.now(tz=timezone.utc),
    )
    xml = generate_gamelist([result], "snes")
    root = ET.fromstring(xml)
    game = root.find("game")
    assert game.find("name").text == "Test"
    assert game.find("desc") is None
    assert game.find("genre") is None


def test_generate_gamelist_multiple_games():
    results = [_make_result(name="Game 1"), _make_result(name="Game 2")]
    xml = generate_gamelist(results, "snes")
    root = ET.fromstring(xml)
    games = root.findall("game")
    assert len(games) == 2
    assert games[0].find("name").text == "Game 1"
    assert games[1].find("name").text == "Game 2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_gamelist_xml.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/output/gamelist_xml.py
"""Generator for EmulationStation gamelist.xml files.

Produces XML compatible with ES: paths relative to system path,
releasedate in %Y%m%dT%H%M%S format, empty tags omitted.
"""

from __future__ import annotations

from xml.dom import minidom
from xml.etree import ElementTree as ET

from multiscraper.models import MediaType, ScrapedResult, ScrapeStatus

# Map MediaType to ES <tag> names
_MEDIA_TAG_MAP = {
    MediaType.IMAGE: "image",
    MediaType.THUMBNAIL: "thumbnail",
    MediaType.VIDEO: "video",
    MediaType.MARQUEE: "marquee",
    MediaType.BOX3D: "box3d",
    MediaType.BACKCOVER: "backcover",
    MediaType.FANART: "fanart",
    MediaType.MANUAL: "manual",
    MediaType.MIXIMAGE: "miximage",
    MediaType.LOGO: "logo",
}


def generate_gamelist(results: list[ScrapedResult], system: str) -> str:
    """Generate a gamelist.xml string for a system.

    Args:
        results: List of ScrapedResult for this system.
        system: System name (unused in output, but for context).

    Returns:
        Pretty-printed XML string with <gameList> root.
    """
    root = ET.Element("gameList")

    for result in results:
        game_elem = ET.SubElement(root, "game")
        rom = result.rom
        ri = rom.rom_id

        # path is always present
        ET.SubElement(game_elem, "path").text = ri.rel_path

        # metadata fields (only if present)
        md = result.metadata
        if md:
            ET.SubElement(game_elem, "name").text = md.name
            if md.desc:
                ET.SubElement(game_elem, "desc").text = md.desc
            if md.rating is not None:
                ET.SubElement(game_elem, "rating").text = f"{md.rating:.2f}"
            if md.releasedate:
                ET.SubElement(game_elem, "releasedate").text = md.releasedate.strftime("%Y%m%dT%H%M%S")
            if md.developer:
                ET.SubElement(game_elem, "developer").text = md.developer
            if md.publisher:
                ET.SubElement(game_elem, "publisher").text = md.publisher
            if md.genre:
                ET.SubElement(game_elem, "genre").text = md.genre
            if md.players is not None:
                ET.SubElement(game_elem, "players").text = str(md.players)
            if md.sortname:
                ET.SubElement(game_elem, "sortname").text = md.sortname

        # media (only if downloaded)
        for mf in result.media:
            tag_name = _MEDIA_TAG_MAP.get(mf.type)
            if tag_name:
                ET.SubElement(game_elem, tag_name).text = f"./downloaded_images/{system}/{mf.local_path}"

    # Pretty print
    rough = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough)
    return dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_gamelist_xml.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/output/gamelist_xml.py tests/unit/test_gamelist_xml.py
git commit -m "feat: add gamelist.xml generator compatible with EmulationStation"
```

---

## Task 3.4: Summary and log JSONL writers

**Depends on:** Task 3.1 (Database for RunTotals).

**Files:**
- Create: `src/multiscraper/output/summary.py`
- Create: `src/multiscraper/output/log_jsonl.py`
- Test: `tests/unit/test_summary.py`

**Interfaces:**
- Produces: `write_summary(report: RunReport, path: Path) -> None`, `JsonlLogWriter` (class)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summary.py
"""Tests for summary.json and log JSONL writers."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from multiscraper.models import RunReport, RunTotals
from multiscraper.output.summary import write_summary
from multiscraper.output.log_jsonl import JsonlLogWriter


def test_write_summary_creates_valid_json(tmp_path: Path):
    report = RunReport(
        run_id="01HTEST",
        started_at=datetime.now(tz=timezone.utc),
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_summary.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/output/summary.py
"""Summary.json writer for run reports."""

from __future__ import annotations

import json
from pathlib import Path

from multiscraper.models import RunReport


def write_summary(report: RunReport, path: Path) -> None:
    """Write a RunReport to summary.json.

    Args:
        report: The RunReport to serialize.
        path: Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = report.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
```

```python
# src/multiscraper/output/log_jsonl.py
"""JSONL log writer for structured run events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonlLogWriter:
    """Append-only JSONL log writer."""

    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")

    def log_event(self, event: str, level: str = "INFO", **kwargs: Any) -> None:
        """Write a single log event as a JSON line."""
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": level,
            "event": event,
            **kwargs,
        }
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_summary.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/output/summary.py src/multiscraper/output/log_jsonl.py tests/unit/test_summary.py
git commit -m "feat: add summary.json and JSONL log writers"
```

---

## Milestone Gate

- [ ] `pytest tests/unit/ -v` — all tests pass (db, csv, xml, summary)
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes
- [ ] SQLite migration 0001 applies cleanly