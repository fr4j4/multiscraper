"""SQLite database layer for multiscraper.

Uses aiosqlite for async access. WAL mode for concurrent read/write.
Migrations are applied on init from db/migrations/*.sql files.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
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

    async def create_run(self, config_json: dict[str, Any]) -> str:
        assert self._conn is not None
        run_id = str(ULID())
        now = datetime.now(tz=UTC).isoformat()
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
        """Insert a rom row, or upsert / reuse an existing one.

        Two paths can produce a UNIQUE collision on ``cache_key``:

        - ``(system, rel_path)`` already exists with a different
          ``cache_key`` (e.g. a re-scraped file with a new hash). The
          ``ON CONFLICT(system, rel_path) DO UPDATE`` clause handles
          that case.

        - A *different* file in the same system has the same
          ``cache_key`` (identical content, different ``rel_path``).
          The first insert wins; this second one collides on the
          ``UNIQUE(cache_key)`` constraint because ``(system,
          rel_path)`` does not match. We treat the gemelo as
          belonging to the same content identity and reuse the
          existing row's id.
        """
        assert self._conn is not None
        try:
            await self._conn.execute(
                "INSERT INTO roms (cache_key, system, rel_path, raw_name, "
                "normalized_name, size, mtime, crc32, sha1) VALUES (?, ?, "
                "?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(system, rel_path) DO UPDATE SET "
                "cache_key=excluded.cache_key, size=excluded.size, "
                "mtime=excluded.mtime, crc32=excluded.crc32, "
                "sha1=excluded.sha1, normalized_name=excluded.normalized_name",
                (cache_key, system, rel_path, raw_name, normalized_name,
                 size, mtime, crc32, sha1),
            )
            await self._conn.commit()
        except sqlite3.IntegrityError:
            await self._conn.rollback()
            cursor = await self._conn.execute(
                "SELECT id FROM roms WHERE cache_key = ?", (cache_key,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                raise
            return int(row[0])
        cursor = await self._conn.execute(
            "SELECT id FROM roms WHERE cache_key = ?", (cache_key,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None, f"rom not found after upsert: {cache_key}"
        return int(row[0])

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

    async def get_roms_by_paths(
        self, system: str, rel_paths: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Bulk lookup of roms by (system, rel_path).

        Returns ``{rel_path: row}`` for each path that exists in the
        roms table for the given system. The row includes the
        ``last_scrape_at`` field, fetched as the most recent
        ``scrape_results.fetched_at`` for that rom, or ``None`` if
        the rom has never been successfully scraped.

        Used by discovery to skip the per-file hash when a previously
        scraped rom is unchanged (size + mtime + crc32 + last_scrape_at
        all consistent).
        """
        assert self._conn is not None
        if not rel_paths:
            return {}
        placeholders = ",".join("?" for _ in rel_paths)
        cursor = await self._conn.execute(
            f"SELECT r.id, r.rel_path, r.cache_key, r.size, r.mtime, "
            f"r.crc32, r.sha1, "
            f"(SELECT MAX(s.fetched_at) FROM scrape_results s "
            f" WHERE s.rom_id = r.id) AS last_scrape_at "
            f"FROM roms r "
            f"WHERE r.system = ? AND r.rel_path IN ({placeholders})",
            [system, *rel_paths],
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {
            row[1]: {
                "id": row[0],
                "rel_path": row[1],
                "cache_key": row[2],
                "size": row[3],
                "mtime": row[4],
                "crc32": row[5],
                "sha1": row[6],
                "last_scrape_at": row[7],
            }
            for row in rows
        }

    async def get_last_scrape_result(
        self, rom_id: int,
    ) -> dict[str, Any] | None:
        """Return the most recent scrape result for a ROM, or None."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT s.status, s.chosen_provider, s.match_score, s.fetched_at, r.crc32, r.sha1 "
            "FROM scrape_results s JOIN roms r ON s.rom_id = r.id "
            "WHERE s.rom_id = ? "
            "ORDER BY s.fetched_at DESC LIMIT 1",
            (rom_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "status": row[0],
            "chosen_provider": row[1],
            "match_score": row[2],
            "fetched_at": row[3],
            "crc32": row[4],
            "sha1": row[5],
        }

    async def get_rom_id_by_cache_key(self, cache_key: str) -> int | None:
        """Return the rom id for a cache_key, or None."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id FROM roms WHERE cache_key = ?", (cache_key,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else None

    async def delete_rom(self, rom_id: int) -> None:
        """Delete a ROM and all its scrape results."""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM roms WHERE id = ?", (rom_id,))
        await self._conn.commit()

    async def insert_scrape_result(self, run_id: str, rom_id: int, result: ScrapedResult) -> None:
        assert self._conn is not None
        now = datetime.now(tz=UTC).isoformat()
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
        ext: str, local_path: str, bytes: int, sha256: str, url: str,
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO media (run_id, rom_id, type, source, ext, local_path, "
            "bytes, sha256, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(rom_id, type) DO UPDATE SET local_path=excluded.local_path, "
            "bytes=excluded.bytes, sha256=excluded.sha256",
            (run_id, rom_id, media_type, source, ext, local_path, bytes, sha256, url),
        )
        await self._conn.commit()

    async def get_override_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT cache_key, name, desc, image_path, metadata_json, "
            "media_paths_json, confidence, note "
            "FROM source_overrides WHERE cache_key = ?",
            (cache_key,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "cache_key": row[0], "name": row[1], "desc": row[2],
            "image_path": row[3], "metadata_json": row[4],
            "media_paths_json": row[5], "confidence": row[6], "note": row[7],
        }

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

    async def truncate_discovered_roms(self) -> None:
        """Empty the per-run discovery table. Called at start and end of run."""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM discovered_roms")
        await self._conn.commit()

    async def insert_discovered_pending(
        self,
        run_id: str,
        system: str,
        entries: list[dict[str, Any]],
    ) -> None:
        """Bulk-insert discovery entries with status 'pending'.

        Each entry dict must have: rel_path, raw_name, normalized_name,
        size, mtime. cache_key/crc32/sha1 are optional (cache_key is
        filled in once the hash is computed).
        """
        assert self._conn is not None
        if not entries:
            return
        now = datetime.now(tz=UTC).isoformat()
        params = [
            (
                run_id, system, e["rel_path"], e["raw_name"], e["normalized_name"],
                int(e.get("size", 0)), int(e.get("mtime", 0)),
                e.get("crc32"), e.get("sha1"),
                e.get("cache_key") or None, "pending", now,
            )
            for e in entries
        ]
        await self._conn.executemany(
            "INSERT INTO discovered_roms (run_id, system, rel_path, raw_name, "
            "normalized_name, size, mtime, crc32, sha1, cache_key, hash_status, "
            "claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, rel_path) DO NOTHING",
            params,
        )
        await self._conn.commit()

    async def find_pending_discovered_id(
        self,
        run_id: str,
        system: str,
        rel_path: str,
    ) -> int | None:
        """Return the row id of a pending entry, or None."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id FROM discovered_roms "
            "WHERE run_id = ? AND system = ? AND rel_path = ? "
            "AND hash_status = 'pending'",
            (run_id, system, rel_path),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else None

    async def update_discovered_hash(
        self,
        row_id: int,
        *,
        size: int,
        mtime: int,
        crc32: str | None,
        sha1: str | None,
        cache_key: str,
        status: str,
        skip_reason: str | None = None,
    ) -> None:
        """Set the hash/size/mtime/cache_key and transition out of 'pending'."""
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE discovered_roms SET size = ?, mtime = ?, crc32 = ?, "
            "sha1 = ?, cache_key = ?, hash_status = ?, skip_reason = ? "
            "WHERE id = ?",
            (size, mtime, crc32, sha1, cache_key or None, status, skip_reason, row_id),
        )
        await self._conn.commit()

    async def claim_one_discovered(
        self,
        run_id: str,
        system: str,
    ) -> dict[str, Any] | None:
        """Atomically claim the next ready row for processing.

        A row is 'ready' if its hash_status is 'done', 'skipped', or
        'failed'. The claim flips hash_status to 'claimed' and stamps
        claimed_at. Returns the row dict, or None if nothing is ready.
        """
        assert self._conn is not None
        now = datetime.now(tz=UTC).isoformat()
        await self._conn.execute(
            "UPDATE discovered_roms SET hash_status = 'claimed', claimed_at = ? "
            "WHERE id = ("
            "  SELECT id FROM discovered_roms "
            "  WHERE run_id = ? AND system = ? "
            "    AND hash_status IN ('done', 'skipped', 'failed') "
            "  ORDER BY id ASC LIMIT 1"
            ") AND hash_status IN ('done', 'skipped', 'failed')",
            (now, run_id, system),
        )
        await self._conn.commit()
        cursor = await self._conn.execute(
            "SELECT id, system, rel_path, raw_name, normalized_name, size, "
            "mtime, crc32, sha1, cache_key, hash_status, skip_reason "
            "FROM discovered_roms WHERE run_id = ? AND system = ? "
            "AND hash_status = 'claimed' AND claimed_at = ? "
            "ORDER BY id DESC LIMIT 1",
            (run_id, system, now),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0], "system": row[1], "rel_path": row[2], "raw_name": row[3],
            "normalized_name": row[4], "size": row[5], "mtime": row[6],
            "crc32": row[7], "sha1": row[8], "cache_key": row[9],
            "hash_status": row[10], "skip_reason": row[11],
        }

    async def release_discovered(self, row_id: int, status: str = "done") -> None:
        """Release a claimed row. Use 'done' for retry, 'completed' for final."""
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE discovered_roms SET hash_status = ?, claimed_at = NULL "
            "WHERE id = ?",
            (status, row_id),
        )
        await self._conn.commit()

    async def mark_completed(self, row_id: int) -> None:
        """Mark a row as fully processed. Will never be re-claimed."""
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE discovered_roms SET hash_status = 'completed', "
            "claimed_at = NULL WHERE id = ?",
            (row_id,),
        )
        await self._conn.commit()

    async def count_discovered(
        self,
        run_id: str,
        system: str | None = None,
        hash_status: str | None = None,
    ) -> int:
        """Count rows in discovered_roms with optional filters."""
        assert self._conn is not None
        clauses = ["run_id = ?"]
        params: list[Any] = [run_id]
        if system is not None:
            clauses.append("system = ?")
            params.append(system)
        if hash_status is not None:
            clauses.append("hash_status = ?")
            params.append(hash_status)
        cursor = await self._conn.execute(
            f"SELECT COUNT(*) FROM discovered_roms WHERE {' AND '.join(clauses)}",
            params,
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else 0

    async def has_in_progress_discovered(self, run_id: str) -> bool:
        """Return True if there is any pending or claimed row left for run_id."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT 1 FROM discovered_roms WHERE run_id = ? "
            "AND hash_status IN ('pending', 'claimed') LIMIT 1",
            (run_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None
