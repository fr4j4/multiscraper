"""Tests for CLI commands."""

from unittest.mock import patch

from click.testing import CliRunner

from multiscraper.cli import main
from multiscraper.doctor import CheckResult, CheckStatus, DoctorReport


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


def _make_report(*results: CheckResult) -> DoctorReport:
    report = DoctorReport()
    report.checks.extend(results)
    return report


def test_cli_doctor_exit_code_clean():
    runner = CliRunner()
    report = _make_report(
        CheckResult(name="python", status=CheckStatus.OK, message="Python 3.12"),
        CheckResult(name="disk_space", status=CheckStatus.OK, message="10.0 GB free"),
    )
    with patch("multiscraper.cli.run_doctor", return_value=report):
        result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0


def test_cli_doctor_exit_code_warn():
    runner = CliRunner()
    report = _make_report(
        CheckResult(name="python", status=CheckStatus.OK, message="Python 3.12"),
        CheckResult(name="cache_db", status=CheckStatus.WARN, message="missing"),
    )
    with patch("multiscraper.cli.run_doctor", return_value=report):
        result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1


def test_cli_doctor_exit_code_fail():
    runner = CliRunner()
    report = _make_report(
        CheckResult(name="python", status=CheckStatus.FAIL, message="too old"),
    )
    with patch("multiscraper.cli.run_doctor", return_value=report):
        result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 2


def test_cli_doctor_summary_printed():
    runner = CliRunner()
    report = _make_report(
        CheckResult(name="python", status=CheckStatus.OK, message="Python 3.12"),
        CheckResult(name="cache_db", status=CheckStatus.WARN, message="missing"),
        CheckResult(name="dependencies", status=CheckStatus.FAIL, message="bad"),
    )
    with patch("multiscraper.cli.run_doctor", return_value=report):
        result = runner.invoke(main, ["doctor"])
    assert "Summary:" in result.output
    assert "1 OK" in result.output
    assert "1 WARN" in result.output
    assert "1 FAIL" in result.output
