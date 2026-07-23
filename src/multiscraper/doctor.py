"""Doctor diagnostic sweep.

Runs a series of checks against the local environment, configuration,
SSH profiles, provider credentials, and disk space. Used by the
`multiscraper doctor` CLI command to help users diagnose setup issues.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from multiscraper.config.loader import resolve_env_vars
from multiscraper.transport.ssh import SshTransport

if TYPE_CHECKING:
    from multiscraper.config.models import ProviderEntry


class CheckStatus(StrEnum):
    """Result status of a doctor check."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"

@dataclass(frozen=True)
class CheckResult:
    """A single doctor check result."""

    name: str
    status: CheckStatus
    message: str


@dataclass
class DoctorReport:
    """Aggregate of all doctor check results."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks)

    def by_status(self, status: CheckStatus) -> list[CheckResult]:
        return [c for c in self.checks if c.status == status]


_ENV_VAR_PATTERN = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def _extract_env_vars(value: object) -> list[str]:
    """Extract env var names referenced in a YAML value (handles strings and dicts)."""
    found: list[str] = []

    def _walk(v: object) -> None:
        if isinstance(v, str):
            found.extend(_ENV_VAR_PATTERN.findall(v))
        elif isinstance(v, dict):
            for vv in v.values():
                _walk(vv)
        elif isinstance(v, list):
            for vv in v:
                _walk(vv)

    _walk(value)
    return found


class Doctor:
    """Run diagnostic checks for the multiscraper setup."""

    MIN_PYTHON = (3, 11)
    DISK_WARN_THRESHOLD_BYTES = 500 * 1024 * 1024

    def check_python_version(self) -> CheckResult:
        v = sys.version_info
        ok = (v.major, v.minor) >= self.MIN_PYTHON
        status = CheckStatus.OK if ok else CheckStatus.FAIL
        msg = f"Python {v.major}.{v.minor}.{v.micro}"
        if not ok:
            req = ".".join(str(p) for p in self.MIN_PYTHON)
            msg += f" (need >= {req})"
        return CheckResult(name="python", status=status, message=msg)

    def check_sources_config(
        self, config_path: Path | None = None
    ) -> CheckResult:
        from multiscraper.config.loader import load_config

        path = config_path or Path("config/sources.yaml")
        if not path.exists():
            return CheckResult(
                name="sources_config",
                status=CheckStatus.FAIL,
                message=f"{path} not found",
            )
        try:
            cfg = load_config(path)
        except Exception as exc:
            return CheckResult(
                name="sources_config",
                status=CheckStatus.FAIL,
                message=f"invalid: {exc}",
            )
        enabled = [p.id for p in cfg.providers if p.enabled]
        return CheckResult(
            name="sources_config",
            status=CheckStatus.OK,
            message=f"{len(enabled)} enabled ({', '.join(enabled)})",
        )

    def check_systems_config(
        self, config_path: Path | None = None
    ) -> CheckResult:
        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return CheckResult(
                name="systems_config",
                status=CheckStatus.WARN,
                message=f"{path} not found (will auto-discover es_systems.cfg)",
            )
        return CheckResult(
            name="systems_config",
            status=CheckStatus.OK,
            message=f"{path} present",
        )

    def check_es_systems(self, override_path: Path | None = None) -> CheckResult:
        from multiscraper.config.es_systems_parser import parse_es_systems

        candidates: list[Path] = []
        if override_path:
            candidates.append(override_path)
        candidates.append(Path.home() / ".emulationstation" / "es_systems.cfg")
        candidates.append(Path("/etc/emulationstation/es_systems.cfg"))

        for path in candidates:
            if path.exists():
                try:
                    systems = parse_es_systems(path)
                except Exception as exc:
                    return CheckResult(
                        name="es_systems",
                        status=CheckStatus.WARN,
                        message=f"found {path} but failed to parse: {exc}",
                    )
                return CheckResult(
                    name="es_systems",
                    status=CheckStatus.OK,
                    message=f"{path} — {len(systems)} system(s)",
                )

        return CheckResult(
            name="es_systems",
            status=CheckStatus.WARN,
            message="not found (no auto-discovery candidates)",
        )

    def check_disk_space(self, path: Path | None = None) -> CheckResult:
        target = path or Path.home() / "multiscraper_data" / "media"
        target = target.expanduser()
        check_path = target
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent
        try:
            usage = shutil.disk_usage(check_path)
        except Exception as exc:
            return CheckResult(
                name="disk_space",
                status=CheckStatus.WARN,
                message=f"cannot check {check_path}: {exc}",
            )
        free_gb = usage.free / (1024**3)
        if usage.free < self.DISK_WARN_THRESHOLD_BYTES:
            return CheckResult(
                name="disk_space",
                status=CheckStatus.WARN,
                message=f"{free_gb:.1f} GB free in {check_path} (low)",
            )
        return CheckResult(
            name="disk_space",
            status=CheckStatus.OK,
            message=f"{free_gb:.1f} GB free in {check_path}",
        )

    def check_provider_credentials(
        self, providers: list[ProviderEntry]
    ) -> CheckResult:
        import os

        missing: list[str] = []
        for entry in providers:
            if not entry.enabled:
                continue
            for var in _extract_env_vars(entry.config):
                if not os.environ.get(var):
                    missing.append(f"{entry.id}:{var}")
        if missing:
            return CheckResult(
                name="provider_credentials",
                status=CheckStatus.FAIL,
                message="missing env vars: " + ", ".join(missing),
            )
        return CheckResult(
            name="provider_credentials",
            status=CheckStatus.OK,
            message="all required env vars present",
        )

    def check_ssh_profile(
        self,
        profile_name: str,
        profile: dict[str, object],
    ) -> CheckResult:
        resolved: dict[str, object] = {
            k: resolve_env_vars(v) if isinstance(v, str) else v
            for k, v in profile.items()
        }

        def _coerce_bool(v: object) -> bool:
            return v if isinstance(v, bool) else False

        def _coerce_int(v: object, default: int) -> int:
            if isinstance(v, int) and not isinstance(v, bool):
                return v
            if isinstance(v, str) and v:
                try:
                    return int(v)
                except ValueError:
                    return default
            return default

        kh = resolved.get("known_hosts")
        if isinstance(kh, str) and kh:
            kh = str(Path(kh).expanduser())

        try:
            import asyncio

            user_raw = resolved.get("user")
            pwd_raw = resolved.get("password")
            key_raw = resolved.get("key_file")
            transport = SshTransport(
                host=str(resolved.get("host", "")),
                port=_coerce_int(resolved.get("port"), 22),
                user=user_raw if isinstance(user_raw, str) else None,
                password=pwd_raw if isinstance(pwd_raw, str) else None,
                key_file=key_raw if isinstance(key_raw, str) else None,
                known_hosts=kh if isinstance(kh, str) else None,
                auto_trust=_coerce_bool(resolved.get("auto_trust")),
            )
            asyncio.run(transport._ensure_connected())
        except Exception as exc:
            return CheckResult(
                name=f"ssh[{profile_name}]",
                status=CheckStatus.FAIL,
                message=f"{exc}",
            )
        host = resolved.get("host", "?")
        user = resolved.get("user", "?")
        return CheckResult(
            name=f"ssh[{profile_name}]",
            status=CheckStatus.OK,
            message=f"{user}@{host} reachable",
        )

    def check_ssh_profiles(
        self, config_path: Path | None = None
    ) -> list[CheckResult]:
        from typing import cast

        import yaml

        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        profiles_obj = raw.get("ssh_profiles", {}) if isinstance(raw, dict) else {}
        profiles = cast(dict[str, dict[str, object]], profiles_obj)
        return [
            self.check_ssh_profile(name, profile)
            for name, profile in profiles.items()
        ]


def run_doctor(ssh_profile: str | None = None) -> DoctorReport:
    """Run all doctor checks and return a report."""
    doctor = Doctor()
    report = DoctorReport()

    report.checks.append(doctor.check_python_version())
    report.checks.append(doctor.check_sources_config())
    report.checks.append(doctor.check_systems_config())
    report.checks.append(doctor.check_es_systems())
    report.checks.append(doctor.check_disk_space())

    try:
        from multiscraper.config.loader import load_config

        cfg = load_config(Path("config/sources.yaml"))
        report.checks.append(doctor.check_provider_credentials(cfg.providers))
    except Exception:
        pass

    report.checks.extend(doctor.check_ssh_profiles())

    if ssh_profile:
        already_checked = any(
            c.name == f"ssh[{ssh_profile}]" for c in report.checks
        )
        if not already_checked:
            from typing import cast

            import yaml

            systems_path = Path("config/systems.yaml")
            if systems_path.exists():
                raw = yaml.safe_load(systems_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    profiles_obj = raw.get("ssh_profiles", {})
                    profiles = cast(dict[str, dict[str, object]], profiles_obj)
                    profile = profiles.get(ssh_profile)
                    if profile:
                        report.checks.append(
                            doctor.check_ssh_profile(ssh_profile, profile)
                        )

    return report
