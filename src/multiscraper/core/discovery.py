"""Discovery: populate the temporary discovered_roms table in parallel.

Discovery is the part of a scrape that, given a transport, lists ROM
files, computes size/mtime/hash, and writes one row per ROM to the
discovered_roms table. The orchestrator (workers) reads from this
table. Running discovery and workers concurrently in the same event
loop removes the serial startup cost of large collections.

When the cache already has a row for a file with matching size,
mtime, and a non-null crc32, and the file's mtime is not older than
the last successful scrape, the hash is skipped and the existing
``cache_key`` is reused. The worker then applies the existing skip
path and the row is recorded as SKIPPED. With ``force_rescrape``
true, the hash is always recomputed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from multiscraper.config.models import System
from multiscraper.output.db import Database
from multiscraper.transport.local import LocalTransport
from multiscraper.transport.ssh import SshTransport

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryStats:
    """Counts for a single discovery pass."""

    listed: int = 0
    hashed: int = 0
    skipped_hash: int = 0
    hash_failed: int = 0


def _normalize_exts(extensions: list[str]) -> set[str]:
    return {e.lower().lstrip(".") for e in extensions}


def _filter_by_extension(files: list[str], extensions: list[str]) -> list[str]:
    if not extensions:
        return files
    exts = _normalize_exts(extensions)
    return [
        f for f in files
        if "." in f and f.rsplit(".", 1)[-1].lower() in exts
    ]


def _normalize_name(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


async def _list_files(
    transport: LocalTransport | SshTransport, system_path: str,
) -> list[str]:
    try:
        entries = await transport.list_dir(system_path)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("list_dir_failed path=%s err=%s", system_path, exc)
        return []
    if isinstance(transport, LocalTransport):
        return [e for e in entries if os.path.isfile(os.path.join(system_path, e))]
    return entries


async def _file_info(
    transport: LocalTransport | SshTransport, full_path: str,
) -> tuple[int, int]:
    try:
        info = await transport.file_info(full_path)
        return info.size, int(info.mtime)
    except Exception as exc:
        logger.warning("file_info_failed path=%s err=%s", full_path, exc)
        return 0, 0


async def discover_system(
    db: Database,
    transport: LocalTransport | SshTransport,
    run_id: str,
    system: System,
    system_path: str,
    *,
    hash_algo: str = "crc32",
    concurrency: int = 32,
    limit: int | None = None,
    force_rescrape: bool = False,
) -> DiscoveryStats:
    """Discover ROMs for one system and populate discovered_roms in parallel.

    Steps:
      1. list_dir -> filter by extension.
      2. bulk-insert one 'pending' row per file (cache_key is NULL until
         the hash is computed).
      3. for each row, in parallel under a semaphore: file_info + hash,
         then UPDATE the row with size, mtime, hash, cache_key and
         status done/failed. The hash is skipped when the cache row
         has matching size + mtime + a non-null crc32 and the mtime
         is not older than the last successful scrape (``--force-
         rescrape`` always re-hashes).
    """
    files = await _list_files(transport, system_path)
    files = _filter_by_extension(files, system.extensions)
    if limit is not None:
        files = files[:limit]

    if not files:
        return DiscoveryStats(listed=0)

    pending_entries: list[dict[str, object]] = [
        {
            "rel_path": f,
            "raw_name": f,
            "normalized_name": _normalize_name(f),
            "size": 0,
            "mtime": 0,
            "cache_key": "",
        }
        for f in files
    ]
    await db.insert_discovered_pending(run_id, system.name, pending_entries)

    existing: dict[str, dict[str, object]] = {}
    if not force_rescrape:
        existing = await db.get_roms_by_paths(system.name, files)

    sem = asyncio.Semaphore(max(1, concurrency))
    stats = DiscoveryStats(listed=len(files))

    def _should_skip_hash(
        cached: dict[str, object] | None, size: int, mtime: int,
    ) -> bool:
        """Decide whether to reuse a cached cache_key instead of re-hashing."""
        if cached is None:
            return False
        crc32 = cached.get("crc32")
        if crc32 is None or crc32 == "":
            return False
        cached_size = cached.get("size")
        cached_mtime = cached.get("mtime")
        if not isinstance(cached_size, int) or cached_size != size:
            return False
        if not isinstance(cached_mtime, int) or cached_mtime != mtime:
            return False
        last_scrape_at = cached.get("last_scrape_at")
        if not isinstance(last_scrape_at, str) or not last_scrape_at:
            return False
        try:
            last_ts = int(
                datetime.fromisoformat(last_scrape_at.replace("Z", "+00:00")).timestamp(),
            )
        except (TypeError, ValueError):
            return False
        return mtime >= last_ts

    async def _process(filename: str) -> None:
        async with sem:
            full_path = f"{system_path.rstrip('/')}/{filename}"
            row_id = await db.find_pending_discovered_id(
                run_id, system.name, filename,
            )
            if row_id is None:
                return
            try:
                size, mtime = await _file_info(transport, full_path)
            except Exception as exc:
                logger.warning("file_info_failed path=%s err=%s", full_path, exc)
                await db.update_discovered_hash(
                    row_id,
                    size=0, mtime=0,
                    crc32=None, sha1=None,
                    cache_key="",
                    status="failed", skip_reason=str(exc),
                )
                stats.hash_failed += 1
                return

            cached = existing.get(filename)
            if _should_skip_hash(cached, size, mtime):
                assert cached is not None
                cached_crc32 = cached.get("crc32")
                cached_sha1 = cached.get("sha1")
                cached_cache_key_raw = cached.get("cache_key")
                cached_cache_key = (
                    cached_cache_key_raw if isinstance(cached_cache_key_raw, str) else ""
                )
                await db.update_discovered_hash(
                    row_id,
                    size=size, mtime=mtime,
                    crc32=cached_crc32 if isinstance(cached_crc32, str) else None,
                    sha1=cached_sha1 if isinstance(cached_sha1, str) else None,
                    cache_key=cached_cache_key,
                    status="done",
                )
                stats.skipped_hash += 1
                return

            try:
                if hash_algo not in ("crc32", "sha1"):
                    raise ValueError(
                        f"hash_algo must be 'crc32' or 'sha1', got {hash_algo!r}",
                    )
                rom_hash = await transport.hash(full_path, hash_algo)  # type: ignore[arg-type]
            except Exception as exc:
                logger.warning("hash_failed path=%s err=%s", full_path, exc)
                await db.update_discovered_hash(
                    row_id,
                    size=size, mtime=mtime,
                    crc32=None, sha1=None,
                    cache_key="",
                    status="failed", skip_reason=str(exc),
                )
                stats.hash_failed += 1
                return
            cache_key = f"{system.name}:{filename}:{rom_hash}"
            crc32 = rom_hash if hash_algo == "crc32" else None
            sha1 = rom_hash if hash_algo == "sha1" else None
            await db.update_discovered_hash(
                row_id,
                size=size, mtime=mtime,
                crc32=crc32, sha1=sha1,
                cache_key=cache_key, status="done",
            )
            stats.hashed += 1

    await asyncio.gather(*(_process(f) for f in files))
    return stats
