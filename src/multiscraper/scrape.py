"""End-to-end skeleton for the `multiscraper scrape` command.

Wires the existing Orchestrator, transport, registry, database, and CSV
writer into a single function that the CLI calls. Discovery and the
worker pool run concurrently in the same event loop; discovery writes
to the temporary discovered_roms table and workers claim rows from it.
"""

from __future__ import annotations

import asyncio
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
    OrchestratorConfig,
    System,
    SystemsConfig,
    Transport,
    TransportsConfig,
)
from multiscraper.core.discovery import discover_system
from multiscraper.core.orchestrator import Orchestrator
from multiscraper.output.db import Database
from multiscraper.providers.base import AllProvidersBlocked
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
        provider_errors: Counts of cascade-level errors per provider
            (e.g. 429/430/503 responses, exceptions). Populated by the
            orchestrator during the run.
        aborted_reason: Non-empty if the run was aborted, typically
            because every media provider was blocked (rate-limited).
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
    provider_errors: dict[str, int] = field(default_factory=dict)
    aborted_reason: str = ""


def _build_transport(
    current: Transport,
    *,
    hash_semaphore: asyncio.Semaphore | None = None,
) -> LocalTransport | SshTransport:
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
        hash_semaphore=hash_semaphore,
    )


async def _count_results(
    db_path: Path, run_id: str,
) -> tuple[int, int, int, int]:
    """Return (matched, no_match, errors, skipped) by querying the DB."""
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
    skipped = 0
    for status, count in rows:
        if status in ("OK", "PARTIAL"):
            matched += int(count)
        elif status == "NO_MATCH":
            no_match += int(count)
        elif status in ("ERROR", "TIMED_OUT", "BLOCKED"):
            errors += int(count)
        elif status == "SKIPPED":
            skipped += int(count)
    return matched, no_match, errors, skipped


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

    Discovers ROMs via the configured transport (in parallel, writing to
    the discovered_roms table), starts the Orchestrator so workers
    consume the table, and aggregates a SkeletonSummary. Discovery and
    workers run concurrently in the same event loop.

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

    is_ssh = current.kind == "ssh"
    if is_ssh:
        hash_sem = asyncio.Semaphore(transports_cfg.orchestrator.discovery_concurrency_ssh)
    else:
        hash_sem = asyncio.Semaphore(transports_cfg.orchestrator.discovery_concurrency_local)
    built_transport: LocalTransport | SshTransport = (
        transport or _build_transport(current, hash_semaphore=hash_sem)
    )

    db = Database(str(db_path))
    await db.init()
    await db.truncate_discovered_roms()

    try:
        run_id = await db.create_run(
            config_json=sources_config.model_dump(mode="json"),
        )
        summary.run_id = run_id

        discovery_done = asyncio.Event()

        async def _run_discovery() -> None:
            try:
                await _discover_all(
                    db=db,
                    transport=built_transport,
                    run_id=run_id,
                    systems=systems_to_run,
                    current=current,
                    hash_algo=hash_algo,
                    limit=limit,
                    orchestrator_cfg=transports_cfg.orchestrator,
                    force_rescrape=force_rescrape,
                )
            finally:
                discovery_done.set()

        discovery_task = asyncio.create_task(_run_discovery(), name="discovery")

        for system in systems_to_run:
            csv_path = csv_dir / f"scrape_{system.name}.csv"
            with tqdm(
                total=None,
                desc=f"scraping {system.name}",
                unit="rom",
                colour="green",
                disable=not show_progress,
            ) as pbar:
                orchestrator = Orchestrator(
                    registry=registry,
                    config=sources_config,
                    db=db,
                    run_id=run_id,
                    csv_path=csv_path,
                    media_root=media_root,
                    orchestrator=transports_cfg.orchestrator,
                    progress_bar=pbar,
                    skip_existing=skip_existing,
                    force_rescrape=force_rescrape,
                )
                try:
                    await orchestrator.start(
                        [system.name], discovery_done=discovery_done,
                    )
                except AllProvidersBlocked as exc:
                    summary.provider_errors = dict(orchestrator.provider_errors)
                    summary.aborted_reason = str(exc)
                    logger.error(
                        "run_aborted system=%s reason=%s providers=%s",
                        system.name, exc, sorted(exc.blocked_providers),
                    )
                    await orchestrator.close()
                    discovery_done.set()
                    break
                summary.provider_errors.update(orchestrator.provider_errors)
                if orchestrator.aborted_reason and not summary.aborted_reason:
                    summary.aborted_reason = orchestrator.aborted_reason
                await orchestrator.close()

        await discovery_task

        total_matched = 0
        total_no_match = 0
        total_errors = 0
        total_skipped = 0
        for rid in [run_id]:
            m, nm, e, sk = await _count_results(db_path, rid)
            total_matched += m
            total_no_match += nm
            total_errors += e
            total_skipped += sk
        total_listed = sum(
            await asyncio.gather(*[
                db.count_discovered(run_id, system=system.name)
                for system in systems_to_run
            ]),
        )
        await db.truncate_discovered_roms()

        summary.roms_total = total_listed
        summary.roms_matched = total_matched
        summary.roms_no_match = total_no_match
        summary.roms_skipped = total_skipped
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


async def _discover_all(
    *,
    db: Database,
    transport: LocalTransport | SshTransport,
    run_id: str,
    systems: list[System],
    current: Transport,
    hash_algo: str,
    limit: int | None,
    orchestrator_cfg: OrchestratorConfig,
    force_rescrape: bool = False,
) -> None:
    """Run discover_system for each system sequentially (one at a time)."""
    is_ssh = isinstance(transport, SshTransport)
    concurrency = (
        orchestrator_cfg.discovery_concurrency_ssh
        if is_ssh
        else orchestrator_cfg.discovery_concurrency_local
    )
    for system in systems:
        system_path = resolve_path(current, system)
        try:
            stats = await discover_system(
                db=db,
                transport=transport,
                run_id=run_id,
                system=system,
                system_path=system_path,
                hash_algo=hash_algo,
                concurrency=concurrency,
                limit=limit,
                force_rescrape=force_rescrape,
            )
        except Exception as exc:
            logger.exception(
                "discover_system_failed system=%s err=%s", system.name, exc,
            )
            continue
        logger.info(
            "discovery_summary system=%s listed=%d hashed=%d "
            "skipped_hash=%d failed=%d",
            system.name, stats.listed, stats.hashed,
            stats.skipped_hash, stats.hash_failed,
        )
