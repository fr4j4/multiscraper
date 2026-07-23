"""Tests for the doctor diagnostic sweep."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from multiscraper.doctor import CheckStatus, Doctor, DoctorReport, run_doctor


def test_check_status_enum():
    assert CheckStatus.OK.value == "OK"
    assert CheckStatus.WARN.value == "WARN"
    assert CheckStatus.FAIL.value == "FAIL"


def test_doctor_report_init():
    report = DoctorReport(checks=[])
    assert report.checks == []
    assert report.has_failures is False


def test_doctor_report_with_failure():
    from multiscraper.doctor import CheckResult

    report = DoctorReport(
        checks=[
            CheckResult(name="python", status=CheckStatus.OK, message="3.14.5"),
            CheckResult(name="ssh", status=CheckStatus.FAIL, message="denied"),
        ]
    )
    assert report.has_failures is True
    assert len(report.checks) == 2


def test_doctor_report_with_only_warnings():
    from multiscraper.doctor import CheckResult

    report = DoctorReport(
        checks=[
            CheckResult(name="python", status=CheckStatus.OK, message="3.14.5"),
            CheckResult(name="disk", status=CheckStatus.WARN, message="low"),
        ]
    )
    assert report.has_failures is False


def test_check_python_version_ok():
    doctor = Doctor()
    result = doctor.check_python_version()
    assert result.status == CheckStatus.OK
    assert "Python" in result.message


def test_check_python_version_too_old(monkeypatch):
    monkeypatch.setattr(
        "multiscraper.doctor.sys.version_info",
        type("V", (), {"major": 3, "minor": 10, "micro": 0})(),
    )
    doctor = Doctor()
    result = doctor.check_python_version()
    assert result.status == CheckStatus.FAIL


def test_check_sources_config_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doctor = Doctor()
    result = doctor.check_sources_config()
    assert result.status == CheckStatus.FAIL
    assert "not found" in result.message


def test_check_sources_config_valid(tmp_path, monkeypatch):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text("providers:\n  - id: local_override\n    enabled: true\n")
    monkeypatch.chdir(tmp_path)
    doctor = Doctor()
    result = doctor.check_sources_config(config_path=cfg)
    assert result.status == CheckStatus.OK


def test_check_systems_config_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doctor = Doctor()
    result = doctor.check_systems_config()
    assert result.status == CheckStatus.WARN
    assert "not found" in result.message


def test_check_systems_config_present(tmp_path, monkeypatch):
    cfg = tmp_path / "systems.yaml"
    cfg.write_text("ssh_profiles: {}\n")
    monkeypatch.chdir(tmp_path)
    doctor = Doctor()
    result = doctor.check_systems_config(config_path=cfg)
    assert result.status == CheckStatus.OK


def test_check_es_systems_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doctor = Doctor()
    result = doctor.check_es_systems()
    assert result.status == CheckStatus.WARN
    assert "not found" in result.message


def test_check_es_systems_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "es_systems.cfg"
    cfg.write_text(
        '<?xml version="1.0"?>\n<systemList><system>'
        "<name>snes</name><fullname>SNES</fullname>"
        "<path>/roms/snes</path></system></systemList>"
    )
    monkeypatch.setattr(
        "multiscraper.doctor.Path.home", lambda: tmp_path
    )
    doctor = Doctor()
    result = doctor.check_es_systems(override_path=cfg)
    assert result.status == CheckStatus.OK
    assert "1" in result.message


def test_check_disk_space_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "multiscraper.doctor.shutil.disk_usage",
        lambda path: MagicMock(free=10 * 1024**3),
    )
    doctor = Doctor()
    result = doctor.check_disk_space(tmp_path)
    assert result.status == CheckStatus.OK


def test_check_disk_space_low(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "multiscraper.doctor.shutil.disk_usage",
        lambda path: MagicMock(free=100 * 1024**2),
    )
    doctor = Doctor()
    result = doctor.check_disk_space(tmp_path)
    assert result.status == CheckStatus.WARN


def test_check_provider_credentials_missing(monkeypatch):
    """When a provider's required env var is not set, check should FAIL."""
    monkeypatch.delenv("SCREENSCRAPER_DEV_ID", raising=False)
    monkeypatch.delenv("SCREENSCRAPER_DEV_PASSWORD", raising=False)
    from multiscraper.config.models import ProviderEntry

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={"devid": "${env:SCREENSCRAPER_DEV_ID}", "devpassword": "${env:SCREENSCRAPER_DEV_PASSWORD}"},
    )
    doctor = Doctor()
    result = doctor.check_provider_credentials([entry])
    assert result.status == CheckStatus.FAIL
    assert "SCREENSCRAPER_DEV_ID" in result.message


def test_check_provider_credentials_ok(monkeypatch):
    monkeypatch.setenv("SCREENSCRAPER_DEV_ID", "abc")
    monkeypatch.setenv("SCREENSCRAPER_DEV_PASSWORD", "xyz")
    from multiscraper.config.models import ProviderEntry

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={"devid": "${env:SCREENSCRAPER_DEV_ID}", "devpassword": "${env:SCREENSCRAPER_DEV_PASSWORD}"},
    )
    doctor = Doctor()
    result = doctor.check_provider_credentials([entry])
    assert result.status == CheckStatus.OK


def test_check_provider_credentials_disabled_provider_skipped(monkeypatch):
    monkeypatch.delenv("SCREENSCRAPER_DEV_ID", raising=False)
    from multiscraper.config.models import ProviderEntry

    entry = ProviderEntry(
        id="screenscraper",
        enabled=False,
        config={"devid": "${env:SCREENSCRAPER_DEV_ID}"},
    )
    doctor = Doctor()
    result = doctor.check_provider_credentials([entry])
    assert result.status == CheckStatus.OK


def test_run_doctor_default_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.yaml").write_text(
        "providers:\n  - id: local_override\n    enabled: true\n"
    )
    monkeypatch.setattr(
        "multiscraper.doctor.shutil.disk_usage",
        lambda p: MagicMock(free=10 * 1024**3),
    )
    report = run_doctor()
    assert isinstance(report, DoctorReport)
    assert any(c.name == "python" for c in report.checks)
    assert any(c.name == "sources_config" for c in report.checks)


def test_run_doctor_with_ssh_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARCADE_PASS", "test")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.yaml").write_text(
        "providers:\n  - id: local_override\n    enabled: true\n"
    )
    (tmp_path / "config" / "systems.yaml").write_text(
        "ssh_profiles:\n  arcade:\n    host: 192.0.2.1\n    user: u\n    password: ${env:ARCADE_PASS}\n"
    )
    with patch("multiscraper.doctor.SshTransport") as mock:
        instance = MagicMock()
        instance._ensure_connected = MagicMock()
        mock.return_value = instance
        report = run_doctor(ssh_profile="arcade")
        assert any(c.name.startswith("ssh[arcade]") for c in report.checks)
        assert mock.called
