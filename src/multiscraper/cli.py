"""CLI entry point for multiscraper."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from multiscraper import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """multiscraper: parallel multi-source scraper for retro gaming frontends."""


@main.command()
@click.option("--roms-root", default=None, help="Root directory for ROMs (local or ssh://)")
@click.option("--media-root", default=None, help="Root directory for downloaded media")
@click.option("--es-systems", default=None, help="Path to es_systems.cfg")
@click.option("--config", default="config/sources.yaml", help="Path to sources.yaml")
@click.option("--systems", default=None, help="Comma-separated list of systems to scrape")
@click.option("--workers", default=8, help="Number of parallel workers")
@click.option("--batch-size", default=50, help="ROMs per batch")
@click.option("--match-threshold", default=0.7, type=float, help="Minimum match score")
@click.option("--hash", "hash_algo", default="auto", type=click.Choice(["crc32", "sha1", "auto"]))
@click.option("--region", default="wor,us,eu,jp", help="Preferred regions")
@click.option("--language", default="en", help="Preferred language")
@click.option("--skip-existing", is_flag=True, help="Skip ROMs already in cache")
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
def scrape(
    roms_root: str | None,
    media_root: str | None,
    es_systems: str | None,
    config: str,
    systems: str | None,
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
) -> None:
    """Scrape ROMs from multiple sources in parallel."""
    from multiscraper.logging_setup import setup_logging

    setup_logging(
        verbose=verbose, quiet=quiet, log_file=Path(log_file) if log_file else None
    )

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"Error: config file not found: {config}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo("Dry run mode: no downloads, no writes.")
        click.echo(f"  Config: {config}")
        click.echo(f"  Workers: {workers}")
        click.echo(f"  Match threshold: {match_threshold}")
        return

    click.echo(f"Starting scrape with {workers} workers...")
    click.echo("Scrape complete.")


@main.command("validate-config")
@click.option("--config", default="config/sources.yaml", help="Path to sources.yaml")
@click.option("--es-systems", default=None, help="Path to es_systems.cfg")
def validate_config(config: str, es_systems: str | None) -> None:
    """Validate configuration files."""
    from multiscraper.config.loader import load_config

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"Error: config file not found: {config}", err=True)
        sys.exit(1)

    try:
        cfg = load_config(config_path)
        click.echo(f"Config valid: {len(cfg.providers)} providers configured")
        click.echo(f"  Match threshold: {cfg.provider_defaults.match_threshold}")
        click.echo(f"  Workers: {cfg.orchestrator.workers}")
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
def doctor(ssh_profile: str | None) -> None:
    """Run diagnostics: check SSH, providers, credentials, disk space."""
    from multiscraper.doctor import CheckStatus, run_doctor

    click.echo("Running diagnostics...")
    report = run_doctor(ssh_profile=ssh_profile)
    for check in report.checks:
        marker = {
            CheckStatus.OK: "OK",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
        }[check.status]
        click.echo(f"  [{marker}] {check.name}: {check.message}")
    if report.has_failures:
        click.echo("Some checks failed.", err=True)
        sys.exit(1)
    click.echo("All checks passed.")


if __name__ == "__main__":
    main()
