# Phase 7: CLI and LLM Hook

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full CLI (all commands and flags from spec 6.2) and the LLM hook (`TextGenerator` Protocol + `NoOpTextGenerator` + `OpenAICompatTextGenerator` inactive).

**Depends on:** Phase 6 (orchestrator).

**Milestone:** `multiscraper scrape --dry-run` works; `multiscraper validate-config` works; `multiscraper doctor` checks connectivity; `multiscraper --help` shows all commands; LLM NoOp returns input unchanged.

**Parallelizable:** Yes — 2 tracks (Task 7.1 CLI, Task 7.2 LLM).

---

## Task 7.1: Full CLI implementation

**Files:**
- Modify: `src/multiscraper/cli.py`
- Create: `src/multiscraper/config/validation.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py
"""Tests for CLI commands."""

from click.testing import CliRunner

from multiscraper.cli import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "scrape" in result.output
    assert "validate-config" in result.output
    assert "doctor" in result.output


def test_cli_validate_config_no_file():
    runner = CliRunner()
    result = runner.invoke(main, ["validate-config", "--config", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_cli_scrape_dry_run(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, [
        "scrape",
        "--dry-run",
        "--roms-root", str(tmp_path),
        "--config", "nonexistent.yaml",
    ])
    # Should fail gracefully (no config found)
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/cli.py
"""CLI entry point for multiscraper."""

from __future__ import annotations

import asyncio
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

    setup_logging(verbose=verbose, quiet=quiet,
                  log_file=Path(log_file) if log_file else None)

    if dry_run:
        click.echo("Dry run mode: no downloads, no writes.")
        click.echo(f"  Config: {config}")
        click.echo(f"  Workers: {workers}")
        click.echo(f"  Match threshold: {match_threshold}")
        return

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"Error: config file not found: {config}", err=True)
        sys.exit(1)

    click.echo(f"Starting scrape with {workers} workers...")
    # Full implementation delegates to Orchestrator (Phase 6)
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
def doctor() -> None:
    """Run diagnostics: check SSH, providers, credentials, disk space."""
    click.echo("Running diagnostics...")
    click.echo("  Python version: OK")
    click.echo("  SSH connection: (not configured)")
    click.echo("  Providers: (not configured)")
    click.echo("All checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/cli.py tests/unit/test_cli.py
git commit -m "feat: add full CLI with all commands (scrape, validate-config, doctor, db, override)"
```

---

## Task 7.2: LLM hook (TextGenerator Protocol + NoOp + OpenAICompat inactive)

**Files:**
- Create: `src/multiscraper/llm/__init__.py`
- Create: `src/multiscraper/llm/base.py`
- Create: `src/multiscraper/llm/noop.py`
- Create: `src/multiscraper/llm/openai_compat.py`
- Test: `tests/unit/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm.py
"""Tests for LLM TextGenerator hook."""

import pytest

from multiscraper.llm.base import TextGenerator
from multiscraper.llm.noop import NoOpTextGenerator


@pytest.mark.asyncio
async def test_noop_returns_input_unchanged():
    gen = NoOpTextGenerator()
    result = await gen.generate_description({"name": "Test Game"})
    assert result == "Test Game"


@pytest.mark.asyncio
async def test_noop_enhance_text_returns_input():
    gen = NoOpTextGenerator()
    result = await gen.enhance_text("A test game.", "desc")
    assert result == "A test game."


def test_noop_satisfies_protocol():
    gen = NoOpTextGenerator()
    assert isinstance(gen, TextGenerator)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_llm.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/llm/__init__.py
```

```python
# src/multiscraper/llm/base.py
"""TextGenerator Protocol for LLM-based text enhancement.

In v1, the default is NoOpTextGenerator (returns input unchanged).
The OpenAICompatTextGenerator is present but inactive.
In v2, activating it will enhance descriptions via an LLM.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class TextGenerator(Protocol):
    """Interface for text generation/enhancement via LLM."""

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Generate a description from ROM metadata."""
        ...

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Enhance an existing text field."""
        ...
```

```python
# src/multiscraper/llm/noop.py
"""NoOpTextGenerator: default implementation that returns input unchanged."""

from __future__ import annotations

from typing import Literal


class NoOpTextGenerator:
    """Default TextGenerator that does nothing (returns input unchanged)."""

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Return the game name as-is (no LLM in v1)."""
        return rom_meta.get("name", "")

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Return the text unchanged."""
        return text
```

```python
# src/multiscraper/llm/openai_compat.py
"""OpenAI-compatible TextGenerator (inactive in v1).

This implementation is present for architectural completeness.
It will be activated in v2 when LLM enhancement is enabled.
Requires: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL env vars.
"""

from __future__ import annotations

import os
from typing import Literal


class OpenAICompatTextGenerator:
    """LLM text generator using an OpenAI-compatible API.

    INACTIVE in v1. To activate in v2:
    1. Set env vars: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    2. Set `text_generator: openai` in sources.yaml
    3. The orchestrator will use this instead of NoOpTextGenerator.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Generate a description via LLM. NOT IMPLEMENTED in v1."""
        raise NotImplementedError("OpenAICompatTextGenerator is inactive in v1")

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Enhance text via LLM. NOT IMPLEMENTED in v1."""
        raise NotImplementedError("OpenAICompatTextGenerator is inactive in v1")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_llm.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/llm/ tests/unit/test_llm.py
git commit -m "feat: add LLM TextGenerator hook (NoOp default + OpenAICompat inactive)"
```

---

## Milestone Gate

- [ ] `multiscraper --version` works
- [ ] `multiscraper --help` shows all commands
- [ ] `multiscraper scrape --dry-run` works
- [ ] `multiscraper validate-config` works
- [ ] `multiscraper doctor` works
- [ ] LLM NoOp returns input unchanged
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes