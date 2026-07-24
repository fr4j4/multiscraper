"""CLI entry point for multiscraper."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from multiscraper import __version__
from multiscraper.config.loader import load_config as load_sources_config
from multiscraper.config.models import MultiscraperConfig
from multiscraper.doctor import CheckStatus, DoctorReport, run_doctor
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.scrape import SkeletonSummary


def build_sources_config(config_path: Path, match_threshold: float) -> MultiscraperConfig:
    """Load sources.yaml and apply only the match_threshold override.

    Other provider_defaults (timeout_sec, rate_limit_per_sec, ...) come
    straight from YAML and are not overridden by the CLI.
    """
    sources_config = load_sources_config(config_path)
    sources_config.provider_defaults.match_threshold = match_threshold
    return sources_config


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """multiscraper: parallel multi-source scraper for retro gaming frontends."""
    load_dotenv()


@main.command()
@click.option("--roms-root", default=None, help="Root directory for ROMs (local or ssh://)")
@click.option("--media-root", default=None, help="Root directory for downloaded media")
@click.option("--es-systems", default=None, help="Path to es_systems.cfg")
@click.option("--config", default="config/sources.yaml", help="Path to sources.yaml")
@click.option(
    "--config-dir",
    "config_dir",
    default="config",
    help="Directory containing config.yaml, sources.yaml, systems.yaml",
)
@click.option("--systems", default=None, help="Comma-separated list of systems to scrape")
@click.option("--limit", default=None, type=int, help="Maximum ROMs per system to scrape")
@click.option("--workers", default=8, help="Number of parallel workers")
@click.option("--batch-size", default=50, help="ROMs per batch")
@click.option("--match-threshold", default=0.7, type=float, help="Minimum match score")
@click.option("--hash", "hash_algo", default="auto", type=click.Choice(["crc32", "sha1", "auto"]))
@click.option("--region", default="wor,us,eu,jp", help="Preferred regions")
@click.option("--language", default="en", help="Preferred language")
@click.option(
    "--skip-existing/--no-skip-existing",
    default=True,
    help="Skip ROMs already scraped with same hash (default: enabled)",
)
@click.option("--force-rescrape", is_flag=True, help="Ignore cache and re-scrape everything")
@click.option("--continue-run", "continue_run_id", default=None, help="Resume an aborted run")
@click.option("--shutdown-timeout", default=180, type=int, help="Shutdown drain timeout in seconds")
@click.option("--ssh-host", default=None, help="SSH host for remote ROMs")
@click.option("--ssh-user", default=None, help="SSH user")
@click.option("--ssh-key", default=None, help="SSH key file path")
@click.option("--ssh-port", default=22, type=int, help="SSH port")
@click.option("--ssh-jump", default=None, help="SSH ProxyJump host")
@click.option("--auto-trust", is_flag=True, help="Auto-add new SSH hosts to known_hosts")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v, -vv)")
@click.option("-q", "--quiet", is_flag=True, help="Only show warnings and errors")
@click.option("--log-file", default=None, help="Path to log file")
@click.option("--csv", "csv_path", default=None, help="Path to CSV output")
@click.option("--emit", default="both", type=click.Choice(["es", "json", "both"]))
@click.option("--dry-run", is_flag=True, help="Simulate without downloading or writing")
@click.option("--no-media", is_flag=True, help="Only scrape metadata, no media download")
@click.option(
    "--progress/--no-progress",
    default=True,
    help="Show tqdm progress bar (default: enabled)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Skip DB cache lookups (always re-scrape)",
)
def scrape(
    roms_root: str | None,
    media_root: str | None,
    es_systems: str | None,
    config: str,
    config_dir: str,
    systems: str | None,
    limit: int | None,
    workers: int,
    batch_size: int,
    match_threshold: float,
    hash_algo: str,
    region: str,
    language: str,
    skip_existing: bool,
    force_rescrape: bool,
    continue_run_id: str | None,
    shutdown_timeout: int,
    ssh_host: str | None,
    ssh_user: str | None,
    ssh_key: str | None,
    ssh_port: int,
    ssh_jump: str | None,
    auto_trust: bool,
    verbose: int,
    quiet: bool,
    log_file: str | None,
    csv_path: str | None,
    emit: str,
    dry_run: bool,
    no_media: bool,
    no_cache: bool,
    progress: bool,
) -> None:
    """Scrape ROMs from multiple sources in parallel."""
    from multiscraper.logging_setup import setup_logging
    from multiscraper.providers.registry import ProviderRegistry

    setup_logging(
        verbose=verbose, quiet=quiet, log_file=Path(log_file) if log_file else None
    )

    if dry_run:
        click.echo("Dry run mode: no downloads, no writes.")
        click.echo(f"  Config: {config}")
        click.echo(f"  Workers: {workers}")
        click.echo(f"  Match threshold: {match_threshold}")
        if limit is not None:
            click.echo(f"  Limit: {limit}")
        return

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"Error: config file not found: {config}", err=True)
        sys.exit(1)

    cfg_dir = Path(config_dir)
    if not (cfg_dir / "config.yaml").exists():
        click.echo(
            f"Error: config.yaml not found in {config_dir}", err=True,
        )
        sys.exit(1)

    sources_config = build_sources_config(config_path, match_threshold)

    systems_list: list[str] | None = None
    if systems:
        systems_list = [s.strip() for s in systems.split(",") if s.strip()]

    if hash_algo == "auto":
        hash_algo = "crc32"

    db_path = Path("cache.db")
    out_csv_dir = Path(csv_path) if csv_path else Path("./reports")
    media = Path(media_root) if media_root else Path("./media")
    media.mkdir(parents=True, exist_ok=True)

    registry = ProviderRegistry()
    registry.register_all()

    click.echo(f"Starting scrape with {workers} workers...")

    try:
        summary = asyncio.run(
            _run_scrape(
                config_dir=cfg_dir,
                db_path=db_path,
                csv_dir=out_csv_dir,
                media_root=media,
                systems_filter=systems_list,
                limit=limit,
                registry=registry,
                sources_config=sources_config,
                hash_algo=hash_algo,
                skip_existing=skip_existing,
                force_rescrape=force_rescrape,
                show_progress=progress and not quiet,
            )
        )
    except KeyboardInterrupt:
        click.echo("Scrape interrupted.", err=True)
        sys.exit(130)

    click.echo("Scrape complete.")
    click.echo(f"  Run ID: {summary.run_id}")
    click.echo(f"  Systems: {', '.join(summary.systems) or '(none)'}")
    click.echo(f"  ROMs discovered: {summary.roms_total}")
    click.echo(f"  Matched: {summary.roms_matched}")
    click.echo(f"  Skipped: {summary.roms_skipped}")
    click.echo(f"  No match: {summary.roms_no_match}")
    click.echo(f"  Errors: {summary.errors}")
    click.echo(f"  CSV dir: {summary.csv_dir}")
    click.echo(f"  DB: {summary.db_path}")


async def _run_scrape(
    *,
    config_dir: Path,
    db_path: Path,
    csv_dir: Path,
    media_root: Path,
    systems_filter: list[str] | None,
    limit: int | None,
    registry: ProviderRegistry,
    sources_config: MultiscraperConfig,
    hash_algo: str,
    skip_existing: bool,
    force_rescrape: bool,
    show_progress: bool,
) -> SkeletonSummary:
    """Async wrapper: setup providers, then run the skeleton."""
    from multiscraper.scrape import run_scrape_skeleton

    await registry.setup_from_config(
        [p.model_dump(mode="json") for p in sources_config.providers],
    )
    try:
        return await run_scrape_skeleton(
            config_dir=config_dir,
            db_path=db_path,
            csv_dir=csv_dir,
            media_root=media_root,
            systems_filter=systems_filter,
            limit=limit,
            registry=registry,
            sources_config=sources_config,
            hash_algo=hash_algo,
            skip_existing=skip_existing,
            force_rescrape=force_rescrape,
            show_progress=show_progress,
        )
    finally:
        await registry.close_all()


@main.command("validate-config")
@click.option("--config", default="config/config.yaml", help="Path to config.yaml")
@click.option("--sources", default="config/sources.yaml", help="Path to sources.yaml")
@click.option(
    "--systems",
    "systems_path",
    default="config/systems.yaml",
    help="Path to systems.yaml",
)
def validate_config(config: str, sources: str, systems_path: str) -> None:
    """Validate configuration files."""
    from multiscraper.config.loader import (
        load_config,
        load_config_yaml,
        load_systems_yaml,
    )

    cfg_path = Path(config)
    src_path = Path(sources)
    sys_path = Path(systems_path)
    missing = [str(p) for p in (cfg_path, src_path, sys_path) if not p.exists()]
    if missing:
        click.echo(
            f"Config invalid: missing files: {', '.join(missing)}", err=True,
        )
        sys.exit(1)

    try:
        transports = load_config_yaml(cfg_path)
        click.echo(f"Config valid: {len(transports.transports)} transports configured")
        click.echo(f"  current_transport: {transports.current_transport}")
        click.echo(f"  Workers: {transports.orchestrator.workers}")
        sources_cfg = load_config(src_path)
        click.echo(
            f"  Sources: {len(sources_cfg.providers)} providers, "
            f"match threshold: {sources_cfg.provider_defaults.match_threshold}"
        )
        systems_cfg = load_systems_yaml(sys_path)
        click.echo(f"  Systems: {len(systems_cfg.systems)} configured")
    except Exception as exc:
        click.echo(f"Config invalid: {exc}", err=True)
        sys.exit(1)


@main.command("convert-to-es")
@click.option("--run-id", required=True, help="Run ID to convert")
@click.option("--out", default="gamelists", help="Output directory")
def convert_to_es(run_id: str, out: str) -> None:
    """Convert cached results to EmulationStation gamelist.xml format."""
    click.echo(f"Converting run {run_id} to ES format in {out}...")


@main.command("list-systems")
@click.option("--es-systems", default=None, help="Path to es_systems.cfg")
@click.option("--roms-root", default=None, help="Root directory for ROMs")
def list_systems(es_systems: str | None, roms_root: str | None) -> None:
    """List detected systems and ROM counts."""
    click.echo("Listing systems...")


@main.group()
def db() -> None:
    """Database management commands."""


@db.command("stats")
def db_stats() -> None:
    """Show database statistics."""
    click.echo("Database stats...")


@db.command("vacuum")
def db_vacuum() -> None:
    """Vacuum the SQLite database."""
    click.echo("Vacuuming database...")


@main.group()
def override() -> None:
    """Manage local source overrides."""


@override.command("add")
@click.argument("rom_path")
@click.option("--name", default=None, help="Game name override")
@click.option("--image", default=None, help="Image file path")
def override_add(rom_path: str, name: str | None, image: str | None) -> None:
    """Add a local override for a ROM."""
    click.echo(f"Adding override for {rom_path}...")


@override.command("list")
@click.option("--system", default=None, help="Filter by system")
def override_list(system: str | None) -> None:
    """List local overrides."""
    click.echo("Listing overrides...")


@main.command()
@click.option("--ssh", "ssh_profile", default=None, help="SSH profile name from systems.yaml")
@click.option(
    "--systems",
    default=None,
    help="Comma-separated list of systems to validate config for",
)
def doctor(ssh_profile: str | None, systems: str | None) -> None:
    """Run diagnostics: check SSH, providers, credentials, disk space."""
    click.echo("Running diagnostics...")
    systems_list = (
        [s.strip() for s in systems.split(",") if s.strip()]
        if systems
        else None
    )
    report: DoctorReport = run_doctor(
        ssh_profile=ssh_profile, systems=systems_list
    )
    ok = warn = fail = 0
    for check in report.checks:
        marker = {
            CheckStatus.OK: "OK",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
        }[check.status]
        if check.status == CheckStatus.OK:
            ok += 1
        elif check.status == CheckStatus.WARN:
            warn += 1
        else:
            fail += 1
        click.echo(f"  [{marker}] {check.name}: {check.message}")
    click.echo(f"Summary: {ok} OK, {warn} WARN, {fail} FAIL")
    if fail:
        sys.exit(2)
    if warn:
        sys.exit(1)
    click.echo("All checks passed.")


if __name__ == "__main__":
    main()
