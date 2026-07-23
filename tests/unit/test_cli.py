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
