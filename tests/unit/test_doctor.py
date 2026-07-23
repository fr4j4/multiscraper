"""Tests for the doctor diagnostic sweep."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aioresponses import aioresponses

from multiscraper.config.models import ProviderEntry
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
    assert "snes" in result.message


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

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={
            "devid": "${env:SCREENSCRAPER_DEV_ID}",
            "devpassword": "${env:SCREENSCRAPER_DEV_PASSWORD}",
        },
    )
    doctor = Doctor()
    result = doctor.check_provider_credentials([entry])
    assert result.status == CheckStatus.FAIL
    assert "SCREENSCRAPER_DEV_ID" in result.message


def test_check_provider_credentials_ok(monkeypatch):
    monkeypatch.setenv("SCREENSCRAPER_DEV_ID", "abc")
    monkeypatch.setenv("SCREENSCRAPER_DEV_PASSWORD", "xyz")

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={
            "devid": "${env:SCREENSCRAPER_DEV_ID}",
            "devpassword": "${env:SCREENSCRAPER_DEV_PASSWORD}",
        },
    )
    doctor = Doctor()
    result = doctor.check_provider_credentials([entry])
    assert result.status == CheckStatus.OK


def test_check_provider_credentials_disabled_provider_skipped(monkeypatch):
    monkeypatch.delenv("SCREENSCRAPER_DEV_ID", raising=False)

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
        "ssh_profiles:\n  arcade:\n    host: 192.0.2.1\n    user: u\n"
        "    password: ${env:ARCADE_PASS}\n"
    )
    with patch("multiscraper.doctor.SshTransport") as mock:
        instance = MagicMock()
        instance._ensure_connected = MagicMock()
        mock.return_value = instance
        report = run_doctor(ssh_profile="arcade")
        assert any(c.name.startswith("ssh[arcade]") for c in report.checks)
        assert mock.called


def test_check_es_systems_found_truncates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    systems_xml = "<systemList>"
    names = [f"sys{i}" for i in range(15)]
    for name in names:
        systems_xml += (
            f"<system><name>{name}</name><fullname>{name}</fullname>"
            f"<path>/roms/{name}</path></system>"
        )
    systems_xml += "</systemList>"
    cfg = tmp_path / "es_systems.cfg"
    cfg.write_text(f'<?xml version="1.0"?>\n{systems_xml}')
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_es_systems(override_path=cfg)
    assert result.status == CheckStatus.OK
    assert "15" in result.message
    assert "..." in result.message


def test_check_dependencies_all_present(monkeypatch):
    import importlib.metadata as md

    real_version = md.version

    def fake_version(name: str) -> str:
        return {
            "asyncssh": "2.14.0",
            "aiohttp": "3.9.0",
            "lxml": "5.0.0",
            "pydantic": "2.5.0",
            "click": "8.1.0",
            "rich": "13.0.0",
            "aiosqlite": "0.19.0",
            "PyYAML": "6.0.0",
        }.get(name, real_version(name))

    monkeypatch.setattr("importlib.metadata.version", fake_version)
    doctor = Doctor()
    result = doctor.check_dependencies()
    assert result.status == CheckStatus.OK
    assert "all" in result.message.lower()
    assert "8" in result.message


def test_check_dependencies_missing_package(monkeypatch):
    import importlib.metadata as md

    real_version = md.version

    def fake_version(name: str) -> str:
        if name == "asyncssh":
            return "2.0.0"
        return {
            "asyncssh": "2.14.0",
            "aiohttp": "3.9.0",
            "lxml": "5.0.0",
            "pydantic": "2.5.0",
            "click": "8.1.0",
            "rich": "13.0.0",
            "aiosqlite": "0.19.0",
            "PyYAML": "6.0.0",
        }.get(name, real_version(name))

    monkeypatch.setattr("importlib.metadata.version", fake_version)
    doctor = Doctor()
    result = doctor.check_dependencies()
    assert result.status == CheckStatus.FAIL
    assert "asyncssh" in result.message


def test_check_cache_db_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_cache_db()
    assert result.status == CheckStatus.WARN
    assert "not found" in result.message.lower() or "missing" in result.message.lower()


def test_check_cache_db_present_healthy(tmp_path, monkeypatch):
    import sqlite3

    ms_dir = tmp_path / ".multiscraper"
    ms_dir.mkdir()
    db_path = ms_dir / "cache.db"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, started_at TEXT, "
            "finished_at TEXT, status TEXT, config_json TEXT, totals_json TEXT)"
        )
        cur.execute(
            "CREATE TABLE roms (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "cache_key TEXT, system TEXT, rel_path TEXT, raw_name TEXT, "
            "normalized_name TEXT, size INTEGER, mtime INTEGER)"
        )
        cur.execute("INSERT INTO runs VALUES ('r1', '2024-01-01', NULL, 'ok', '{}', '{}')")
        cur.execute(
            "INSERT INTO roms (cache_key, system, rel_path, raw_name, "
            "normalized_name, size, mtime) "
            "VALUES ('k1', 'snes', 'a.sfc', 'a', 'a', 1, 0)"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_cache_db()
    assert result.status == CheckStatus.OK
    assert "runs: 1" in result.message
    assert "roms: 1" in result.message
    assert "integrity: OK" in result.message


def test_check_cache_db_corrupt(tmp_path, monkeypatch):
    ms_dir = tmp_path / ".multiscraper"
    ms_dir.mkdir()
    db_path = ms_dir / "cache.db"
    db_path.write_text("not a sqlite database at all" * 100)
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_cache_db()
    assert result.status == CheckStatus.FAIL


def test_check_media_writable_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_media_writable()
    assert result.status == CheckStatus.OK


def test_check_media_writable_permission_denied(tmp_path, monkeypatch):
    media_root = tmp_path / "multiscraper_data"
    media_root.mkdir()
    media_root.chmod(0o555)
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    try:
        result = doctor.check_media_writable()
        assert result.status == CheckStatus.FAIL
    finally:
        media_root.chmod(0o755)


def test_check_logs_writable_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    result = doctor.check_logs_writable()
    assert result.status == CheckStatus.OK


def test_check_logs_writable_permission_denied(tmp_path, monkeypatch):
    ms_dir = tmp_path / ".multiscraper"
    ms_dir.mkdir()
    ms_dir.chmod(0o555)
    monkeypatch.setattr("multiscraper.doctor.Path.home", lambda: tmp_path)
    doctor = Doctor()
    try:
        result = doctor.check_logs_writable()
        assert result.status == CheckStatus.FAIL
    finally:
        ms_dir.chmod(0o755)


def test_check_output_paths_existing(tmp_path):
    csv_path = tmp_path / "out.csv"
    csv_path.write_text("a,b\n1,2\n")
    gamelist_dir = tmp_path / "gamelists"
    gamelist_dir.mkdir()
    doctor = Doctor()
    results = doctor.check_output_paths(csv_path=csv_path, gamelist_dir=gamelist_dir)
    assert len(results) == 2
    for r in results:
        assert r.status == CheckStatus.WARN
        assert r.message != ""


def test_check_output_paths_missing(tmp_path):
    csv_path = tmp_path / "missing.csv"
    gamelist_dir = tmp_path / "missing_gamelists"
    doctor = Doctor()
    results = doctor.check_output_paths(csv_path=csv_path, gamelist_dir=gamelist_dir)
    assert len(results) == 2
    for r in results:
        assert r.status == CheckStatus.OK


def test_check_output_paths_none():
    doctor = Doctor()
    results = doctor.check_output_paths(csv_path=None, gamelist_dir=None)
    assert results == []


def test_check_provider_endpoints_all_ok():
    from multiscraper.providers.registry import ProviderRegistry
    from multiscraper.providers.screenscraper import ScreenScraperProvider

    reg = ProviderRegistry()
    reg.register_class(ScreenScraperProvider)

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={},
    )

    with aioresponses() as m:
        m.head(ScreenScraperProvider.health_url, status=200)
        results = Doctor().check_provider_endpoints([entry])

    assert len(results) == 1
    assert results[0].name == "endpoint[screenscraper]"
    assert results[0].status == CheckStatus.OK


def test_check_provider_endpoints_one_down():
    from multiscraper.providers.registry import ProviderRegistry
    from multiscraper.providers.screenscraper import ScreenScraperProvider

    reg = ProviderRegistry()
    reg.register_class(ScreenScraperProvider)

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={},
    )

    with aioresponses() as m:
        m.head(ScreenScraperProvider.health_url, status=500)
        results = Doctor().check_provider_endpoints([entry])

    assert len(results) == 1
    assert results[0].name == "endpoint[screenscraper]"
    assert results[0].status == CheckStatus.FAIL


def test_check_provider_loadable_known():
    from multiscraper.providers.registry import ProviderRegistry
    from multiscraper.providers.screenscraper import ScreenScraperProvider

    reg = ProviderRegistry()
    reg.register_class(ScreenScraperProvider)

    entry = ProviderEntry(
        id="screenscraper",
        enabled=True,
        config={"devid": "x", "devpassword": "y"},
    )

    results = Doctor().check_provider_loadable([entry])
    assert len(results) == 1
    assert results[0].name == "loadable[screenscraper]"
    assert results[0].status == CheckStatus.OK


def test_check_provider_loadable_unknown():
    entry = ProviderEntry(
        id="no_such",
        enabled=True,
        config={},
    )

    results = Doctor().check_provider_loadable([entry])
    assert len(results) == 1
    assert results[0].name == "loadable[no_such]"
    assert results[0].status == CheckStatus.FAIL
    assert "not registered" in results[0].message
