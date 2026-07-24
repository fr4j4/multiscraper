"""End-to-end skeleton for the `multiscraper scrape` command.

Wires the existing Orchestrator, transport, registry, database, and CSV
writer into a single function that the CLI calls. Phase 2 delegates
the actual scrape work to `Orchestrator.start` and adds hash
computation (crc32/sha1) on ROM discovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from multiscraper.config.loader import (
    load_config_yaml,
    load_systems_yaml,
    resolve_path,
)
from multiscraper.config.models import (
    MultiscraperConfig,
    SystemsConfig,
    Transport,
    TransportsConfig,
)
from multiscraper.core.orchestrator import Orchestrator
from multiscraper.models import Rom, RomIdentifier
from multiscraper.output.db import Database
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.transport.local import LocalTransport
from multiscraper.transport.ssh import SshTransport

logger = logging.getLogger(__name__)


@dataclass
class SkeletonSummary:
    """Summary of a skeleton scrape run.

    Attributes:
        run_id: ULID of the database run row, or empty string if not started.
        systems: Names of systems that were processed.
        roms_total: Number of ROMs discovered and submitted to the cascade.
        roms_matched: Number of ROMs that produced a successful match.
        roms_no_match: Number of ROMs that produced no match above threshold.
        roms_skipped: Number of ROMs skipped because they already have an OK result.
        errors: Number of ROMs that errored during processing.
        csv_dir: Path to the directory containing per-system CSV reports.
        db_path: Path to the SQLite cache.
    """

    run_id: str = ""
    systems: list[str] = field(default_factory=list)
    roms_total: int = 0
    roms_matched: int = 0
    roms_no_match: int = 0
    roms_skipped: int = 0
    errors: int = 0
    csv_dir: str = ""
    db_path: str = ""


def _build_transport(current: Transport) -> LocalTransport | SshTransport:
    """Instantiate a transport from a config Transport entry."""
    if current.kind == "local":
        return LocalTransport()
    return SshTransport(
        host=current.host or "",
        port=current.port,
        user=current.user,
        password=current.password,
        key_file=current.key_file,
        known_hosts=current.known_hosts,
        auto_trust=current.auto_trust,
    )


async def _list_rom_files(
    transport: LocalTransport | SshTransport, system_path: str, extensions: list[str],
) -> list[str]:
    """List ROMs in system_path, filtered by extension.

    Returns an empty list if the directory is missing or transport fails.
    """
    try:
        all_files = await transport.list_dir(system_path)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("list_dir_failed path=%s err=%s", system_path, exc)
        return []

    exts = {e.lower().lstrip(".") for e in extensions}
    return [
        f for f in all_files
        if "." in f and f.rsplit(".", 1)[-1].lower() in exts
    ]


async def _make_rom(
    transport: LocalTransport | SshTransport,
    system: str,
    system_path: str,
    filename: str,
    hash_algo: str = "crc32",
) -> Rom:
    """Build a Rom object from a transport-discovered file.

    Computes the configured hash (crc32 by default) and stores it in
    `rom.rom_id.crc32` or `rom.rom_id.sha1` depending on the algo.
    """
    full_path = f"{system_path.rstrip('/')}/{filename}"
    try:
        info = await transport.file_info(full_path)
        size = info.size
        mtime = info.mtime
    except OSError as exc:
        logger.warning("file_info_failed path=%s err=%s", full_path, exc)
        size = 0
        mtime = 0

    rom_hash = ""
    if hash_algo not in ("crc32", "sha1"):
        raise ValueError(f"hash_algo must be 'crc32' or 'sha1', got {hash_algo!r}")
    try:
        rom_hash = await transport.hash(full_path, hash_algo)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("hash_failed path=%s err=%s", full_path, exc)

    raw_name = filename
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    cache_key = f"{system}:{filename}:{rom_hash}"
    rom_id = RomIdentifier(
        rel_path=filename,
        size=size,
        mtime=mtime,
        crc32=rom_hash if hash_algo == "crc32" else None,
        sha1=rom_hash if hash_algo == "sha1" else None,
        cache_key=cache_key,
    )
    return Rom(
        system=system,
        rom_id=rom_id,
        raw_name=raw_name,
        normalized_name=stem,
    )


async def _count_results(
    db_path: Path, run_id: str,
) -> tuple[int, int, int]:
    """Return (matched, no_match, errors) by querying the DB."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT status, COUNT(*) FROM scrape_results WHERE run_id = ? "
            "GROUP BY status",
            (run_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    matched = 0
    no_match = 0
    errors = 0
    for status, count in rows:
        if status in ("OK", "PARTIAL"):
            matched += int(count)
        elif status == "NO_MATCH":
            no_match += int(count)
        elif status in ("ERROR", "TIMED_OUT", "BLOCKED"):
            errors += int(count)
    return matched, no_match, errors


async def run_scrape_skeleton(
    *,
    config_dir: Path,
    db_path: Path,
    csv_dir: Path,
    media_root: Path,
    systems_filter: list[str] | None,
    limit: int | None,
    registry: ProviderRegistry,
    sources_config: MultiscraperConfig,
    transport: LocalTransport | SshTransport | None = None,
    hash_algo: str = "crc32",
    skip_existing: bool = True,
    force_rescrape: bool = False,
    show_progress: bool = True,
) -> SkeletonSummary:
    """Run the end-to-end skeleton scrape.

    Discovers ROMs via the configured transport, builds Rom objects
    with hashes, skips those already scraped (if skip_existing), and
    hands the rest to the Orchestrator. The Orchestrator owns the
    worker pool, cascade, media download, DB persistence, and CSV
    writing (one CSV per system, in csv_dir).

    Args:
        config_dir: Directory containing config.yaml, sources.yaml, systems.yaml.
        db_path: Path to the SQLite cache (created if missing).
        csv_dir: Directory where per-system CSV files are written.
        media_root: Root directory for downloaded media.
        systems_filter: If given, only these system names are scraped.
        limit: Optional maximum number of ROMs per system to scrape.
        registry: Provider registry to use for the cascade.
        sources_config: MultiscraperConfig from sources.yaml.
        transport: Optional pre-built transport. If None, builds one
            from the YAML config. Useful for tests.
        hash_algo: Hash algorithm to compute per ROM ("crc32" or "sha1").
        skip_existing: If True, skip ROMs that already have an OK result
            with the same hash in the DB.
        force_rescrape: If True, re-scrape all ROMs regardless of cache.

    Returns:
        A SkeletonSummary describing what happened.
    """
    transports_cfg: TransportsConfig = load_config_yaml(
        config_dir / "config.yaml"
    )
    systems_cfg: SystemsConfig = load_systems_yaml(
        config_dir / "systems.yaml"
    )

    current = next(
        t for t in transports_cfg.transports
        if t.name == transports_cfg.current_transport
    )
    built_transport: LocalTransport | SshTransport = (
        transport or _build_transport(current)
    )

    if systems_filter is not None:
        wanted = set(systems_filter)
        systems_to_run = [
            s for s in systems_cfg.systems if s.name in wanted
        ]
    else:
        systems_to_run = list(systems_cfg.systems)

    system_names = [s.name for s in systems_to_run]
    summary = SkeletonSummary(
        systems=system_names,
        csv_dir=str(csv_dir),
        db_path=str(db_path),
    )
    csv_dir.mkdir(parents=True, exist_ok=True)

    db = Database(str(db_path))
    await db.init()

    try:
        all_roms: list[Rom] = []
        roms_by_system: dict[str, list[Rom]] = {}
        skipped = 0

        for system in systems_to_run:
            system_path = resolve_path(current, system)
            files = await _list_rom_files(
                built_transport, system_path, system.extensions,
            )
            if limit is not None:
                files = files[:limit]
            system_roms: list[Rom] = []
            for filename in files:
                rom = await _make_rom(
                    built_transport,
                    system.name,
                    system_path,
                    filename,
                    hash_algo=hash_algo,
                )
                if skip_existing and not force_rescrape:
                    rom_id = await db.get_rom_id_by_cache_key(rom.rom_id.cache_key)
                    if rom_id is not None:
                        last = await db.get_last_scrape_result(rom_id)
                        same_hash = last is not None and last["crc32"] == rom.rom_id.crc32
                        good_status = last is not None and last["status"] in ("OK", "PARTIAL")
                        if good_status and same_hash:
                            logger.info(
                                "rom_skipped cache_key=%s reason=already_scraped",
                                rom.rom_id.cache_key,
                            )
                            skipped += 1
                            continue
                        if last is not None and not same_hash:
                            await db.delete_rom(rom_id)
                            logger.info(
                                "rom_stale cache_key=%s old_crc=%s new_crc=%s",
                                rom.rom_id.cache_key, last["crc32"], rom.rom_id.crc32,
                            )
                system_roms.append(rom)
            roms_by_system[system.name] = system_roms
            all_roms.extend(system_roms)

        summary.roms_total = len(all_roms)
        summary.roms_skipped = skipped

        if not all_roms:
            return summary

        all_run_ids: list[str] = []
        for system_name, system_roms in roms_by_system.items():
            if not system_roms:
                continue
            csv_path = csv_dir / f"scrape_{system_name}.csv"
            with tqdm(  # type: ignore[call-arg]
                total=len(system_roms),
                desc=f"scraping {system_name}",
                unit="rom",
                colour="green",
                disable=not show_progress,
            ) as pbar:
                orchestrator = Orchestrator(
                    registry=registry,
                    config=sources_config,
                    db_path=str(db_path),
                    csv_path=csv_path,
                    media_root=media_root,
                    orchestrator=transports_cfg.orchestrator,
                    progress_bar=pbar,
                )
                run_id = await orchestrator.start(system_roms, [system_name])
                await orchestrator.close()
            all_run_ids.append(run_id)

        summary.run_id = all_run_ids[0] if all_run_ids else ""
        total_matched = 0
        total_no_match = 0
        total_errors = 0
        for rid in all_run_ids:
            m, nm, e = await _count_results(db_path, rid)
            total_matched += m
            total_no_match += nm
            total_errors += e
        summary.roms_matched = total_matched
        summary.roms_no_match = total_no_match
        summary.errors = total_errors
        return summary
    finally:
        await db.close()
        if transport is None:
            close = getattr(built_transport, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
