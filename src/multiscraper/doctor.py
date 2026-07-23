"""Doctor diagnostic sweep.

Runs a series of checks against the local environment, configuration,
SSH profiles, provider credentials, and disk space. Used by the
`multiscraper doctor` CLI command to help users diagnose setup issues.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import aiohttp

from multiscraper.config.loader import resolve_env_vars
from multiscraper.providers.gamefaqs import GameFAQsProvider
from multiscraper.providers.giantbomb import GiantBombProvider
from multiscraper.providers.hasheous import HasheousIdentifier
from multiscraper.providers.igdb import IGDBProvider
from multiscraper.providers.libretro_thumbnails import LibRetroThumbnailsProvider
from multiscraper.providers.local import LocalProvider
from multiscraper.providers.mobygames import MobyGamesProvider
from multiscraper.providers.openvgdb import OpenVGDBProvider
from multiscraper.providers.rawg import RAWGProvider
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.providers.retroachievements import RetroAchievementsProvider
from multiscraper.providers.screenscraper import ScreenScraperProvider
from multiscraper.providers.thegamesdb import TheGamesDBProvider
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

    REQUIRED_DEPS: ClassVar[dict[str, str]] = {
        "asyncssh": "2.14.0",
        "aiohttp": "3.9.0",
        "lxml": "5.0.0",
        "pydantic": "2.5.0",
        "click": "8.1.0",
        "rich": "13.0.0",
        "aiosqlite": "0.19.0",
        "PyYAML": "6.0.0",
    }

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

    _SYSTEM_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
    _EXT_PATTERN = re.compile(r"^\.?[a-z0-9]{1,8}$")
    _ROMS_ROOT_SSH_PATTERN = re.compile(r"^ssh://[\w@.:-]+")
    _ROMS_ROOT_LOCAL_PATTERN = re.compile(r"^(/[^/].*|~/.*|\./.*|\.\./.*)$")

    def _validate_system_name(self, name: str) -> bool:
        return bool(self._SYSTEM_NAME_PATTERN.match(name))

    def _is_wildcard(self, item: str) -> bool:
        return item == "*"

    def _is_valid_extension(self, item: str) -> bool:
        return bool(self._EXT_PATTERN.match(item))

    def _normalize_extension(self, item: str) -> str:
        return item if item.startswith(".") else f".{item}"

    def _validate_extensions(self, exts: object) -> tuple[CheckStatus, str]:
        if not isinstance(exts, list):
            return CheckStatus.FAIL, "extensions: must be a list"
        if not exts:
            return (
                CheckStatus.FAIL,
                "extensions: empty (use [*] for wildcard or list of extensions)",
            )
        if all(self._is_wildcard(str(x)) for x in exts):
            return CheckStatus.OK, "extensions: wildcard [*]"
        bad = [str(x) for x in exts if not self._is_valid_extension(str(x))]
        if bad:
            detail = ", ".join(f"'{b}'" for b in bad)
            return (
                CheckStatus.FAIL,
                f"extensions: invalid items: {detail}",
            )
        normalized = [self._normalize_extension(str(x)) for x in exts]
        return CheckStatus.OK, f"extensions: {', '.join(normalized)} valid"

    def _validate_roms_root(self, path: object) -> tuple[CheckStatus, str]:
        if not isinstance(path, str) or not path:
            return CheckStatus.FAIL, "roms_root: missing"
        if self._ROMS_ROOT_SSH_PATTERN.match(path):
            return CheckStatus.OK, "roms_root: ssh:// valid"
        if self._ROMS_ROOT_LOCAL_PATTERN.match(path):
            if path.startswith("~"):
                return CheckStatus.OK, "roms_root: local path with ~"
            return CheckStatus.OK, "roms_root: local path"
        return CheckStatus.FAIL, f"roms_root: invalid format '{path}'"

    def _load_es_systems_index(
        self,
    ) -> dict[str, tuple[str, list[str]]]:
        from multiscraper.config.es_systems_parser import parse_es_systems

        candidates: list[Path] = [
            Path.home() / ".emulationstation" / "es_systems.cfg",
            Path("/etc/emulationstation/es_systems.cfg"),
        ]
        for path in candidates:
            if path.exists():
                try:
                    systems = parse_es_systems(path)
                except Exception:
                    continue
                return {s.name: (s.path, list(s.extensions)) for s in systems}
        return {}

    def _load_systems_yaml(
        self, config_path: Path | None = None
    ) -> dict[str, dict[str, object]]:
        from typing import cast

        import yaml

        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return {}
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        systems_obj = raw.get("systems", [])
        systems_list = cast(list[dict[str, object]], systems_obj) if isinstance(
            systems_obj, list
        ) else []
        return {
            str(s.get("name")): s
            for s in systems_list
            if isinstance(s, dict) and isinstance(s.get("name"), str)
        }

    def check_systems_config_names(
        self, names: list[str]
    ) -> list[CheckResult]:
        """Validate system configuration for the given system names.

        Looks up each name in both es_systems.cfg (auto-discovered) and
        config/systems.yaml. Sub-checks expressed in a single
        CheckResult.message: resolvable, source mixing, name format,
        extensions valid, roms_root format valid. Transport is
        inferred from `roms_root`, so no per-system `ssh_profile` is
        consulted.
        """
        results: list[CheckResult] = []
        if not names:
            return results
        es_index = self._load_es_systems_index()
        yaml_systems = self._load_systems_yaml()
        for raw_name in names:
            name = str(raw_name)
            es_entry = es_index.get(name)
            yaml_entry = yaml_systems.get(name)
            parts: list[str] = []
            status = CheckStatus.OK
            if es_entry is None and yaml_entry is None:
                results.append(
                    CheckResult(
                        name=f"system[{name}]",
                        status=CheckStatus.FAIL,
                        message="unknown system (not found in es_systems or systems.yaml)",
                    )
                )
                continue
            sources: list[str] = []
            if es_entry is not None:
                sources.append("es_systems")
            if yaml_entry is not None:
                sources.append("systems.yaml")
            parts.append(f"source={'+'.join(sources)}")
            if es_entry is not None and yaml_entry is None:
                parts.append("no override in systems.yaml")
                if status == CheckStatus.OK:
                    status = CheckStatus.WARN
            if not self._validate_system_name(name):
                parts.append(f"name='{name}' (invalid format)")
                status = CheckStatus.FAIL
            ext_value: object = []
            has_yaml_exts = False
            if yaml_entry is not None and "extensions" in yaml_entry:
                ext_value = yaml_entry.get("extensions")
                has_yaml_exts = True
            elif es_entry is not None:
                ext_value = list(es_entry[1])
            ext_status, ext_msg = self._validate_extensions(ext_value)
            parts.append(ext_msg)
            if ext_status == CheckStatus.FAIL and has_yaml_exts:
                status = CheckStatus.FAIL
            elif ext_status == CheckStatus.FAIL and not has_yaml_exts:
                if not ext_value:
                    parts.append("extensions: missing (use [*] or list of extensions)")
                status = CheckStatus.FAIL
            roms_root_value: object = None
            if yaml_entry is not None and "roms_root" in yaml_entry:
                roms_root_value = yaml_entry.get("roms_root")
            elif es_entry is not None:
                roms_root_value = es_entry[0]
            rr_status, rr_msg = self._validate_roms_root(roms_root_value)
            parts.append(rr_msg)
            if rr_status == CheckStatus.FAIL:
                status = CheckStatus.FAIL
            results.append(
                CheckResult(
                    name=f"system[{name}]",
                    status=status,
                    message=", ".join(parts),
                )
            )
        return results

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
                names = [s.name for s in systems]
                display = ", ".join(names[:10])
                if len(names) > 10:
                    display += ", ..."
                return CheckResult(
                    name="es_systems",
                    status=CheckStatus.OK,
                    message=f"{path} — {len(names)} systems: {display}",
                )

        return CheckResult(
            name="es_systems",
            status=CheckStatus.WARN,
            message="not found (no auto-discovery candidates)",
        )

    def _check_writable(self, path: Path, name: str) -> CheckResult:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / "multiscraper_doctor.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.read_text(encoding="utf-8")
            probe.unlink()
        except Exception as exc:
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"{path} not writable: {exc}",
            )
        return CheckResult(
            name=name,
            status=CheckStatus.OK,
            message=f"{path} writable",
        )

    def check_media_writable(self) -> CheckResult:
        path = Path.home() / "multiscraper_data" / "media"
        return self._check_writable(path, "media_writable")

    def check_logs_writable(self) -> CheckResult:
        path = Path.home() / ".multiscraper" / "logs"
        return self._check_writable(path, "logs_writable")

    def check_dependencies(self) -> CheckResult:
        def _parse(v: str) -> tuple[int, ...]:
            return tuple(int(p) for p in v.split(".") if p.isdigit())

        missing: list[str] = []
        for pkg, minimum in self.REQUIRED_DEPS.items():
            try:
                installed = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                missing.append(f"{pkg}: not installed")
                continue
            if _parse(installed) < _parse(minimum):
                missing.append(f"{pkg}: {installed} found, need >= {minimum}")
        if missing:
            return CheckResult(
                name="dependencies",
                status=CheckStatus.FAIL,
                message="; ".join(missing),
            )
        return CheckResult(
            name="dependencies",
            status=CheckStatus.OK,
            message=f"all {len(self.REQUIRED_DEPS)} packages present",
        )

    def check_cache_db(self) -> CheckResult:
        db_path = Path.home() / ".multiscraper" / "cache.db"
        if not db_path.exists():
            return CheckResult(
                name="cache_db",
                status=CheckStatus.WARN,
                message=f"{db_path} not found (will be created on first run)",
            )
        size_mb = db_path.stat().st_size / (1024 * 1024)
        try:
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA integrity_check")
                integrity_row = cur.fetchone()
                integrity = integrity_row[0] if integrity_row else "?"
                cur.execute("SELECT COUNT(*) FROM runs")
                runs_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM roms")
                roms_count = cur.fetchone()[0]
        except sqlite3.DatabaseError as exc:
            return CheckResult(
                name="cache_db",
                status=CheckStatus.FAIL,
                message=f"integrity check failed: {exc}",
            )
        if integrity != "ok":
            return CheckResult(
                name="cache_db",
                status=CheckStatus.FAIL,
                message=f"integrity: {integrity}, runs: {runs_count}, roms: {roms_count}",
            )
        return CheckResult(
            name="cache_db",
            status=CheckStatus.OK,
            message=(
                f"runs: {runs_count}, roms: {roms_count}, "
                f"integrity: OK, size: {size_mb:.1f} MB"
            ),
        )

    def check_output_paths(
        self,
        csv_path: Path | None,
        gamelist_dir: Path | None,
    ) -> list[CheckResult]:
        results: list[CheckResult] = []
        for label, path in (
            ("output_csv", csv_path),
            ("output_gamelist_dir", gamelist_dir),
        ):
            if path is None:
                continue
            if path.exists():
                results.append(
                    CheckResult(
                        name=label,
                        status=CheckStatus.WARN,
                        message=f"{path} already exists (will be overwritten)",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=label,
                        status=CheckStatus.OK,
                        message=f"{path} does not exist",
                    )
                )
        return results

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

    def _build_provider_registry(self) -> ProviderRegistry:
        """Build a ProviderRegistry with all known provider classes pre-registered."""
        reg = ProviderRegistry()
        for cls in (
            ScreenScraperProvider,
            IGDBProvider,
            RAWGProvider,
            MobyGamesProvider,
            GiantBombProvider,
            RetroAchievementsProvider,
            TheGamesDBProvider,
            LibRetroThumbnailsProvider,
            OpenVGDBProvider,
            GameFAQsProvider,
            HasheousIdentifier,
            LocalProvider,
        ):
            reg.register_class(cls)
        return reg

    def check_provider_endpoints(
        self, providers: list[ProviderEntry]
    ) -> list[CheckResult]:
        """HEAD-check each enabled provider's health_url."""
        results: list[CheckResult] = []
        reg = self._build_provider_registry()
        targets: list[tuple[str, str]] = []
        for entry in providers:
            if not entry.enabled:
                continue
            cls = reg.get_class(entry.id)
            if cls is None:
                continue
            url = getattr(cls, "health_url", None)
            if not url:
                results.append(
                    CheckResult(
                        name=f"endpoint[{entry.id}]",
                        status=CheckStatus.OK,
                        message="skipped (local)",
                    )
                )
                continue
            targets.append((entry.id, url))

        async def _probe_all() -> list[tuple[str, CheckStatus, str]]:
            outcomes: list[tuple[str, CheckStatus, str]] = []
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for pid, url in targets:
                    try:
                        async with session.head(url) as resp:
                            status = resp.status
                    except (aiohttp.ClientError, TimeoutError) as exc:
                        outcomes.append((pid, CheckStatus.FAIL, f"{exc}"))
                        continue
                    if 200 <= status < 400:
                        outcomes.append((pid, CheckStatus.OK, f"HTTP {status}"))
                    elif 400 <= status < 500:
                        outcomes.append((pid, CheckStatus.WARN, f"HTTP {status}"))
                    else:
                        outcomes.append((pid, CheckStatus.FAIL, f"HTTP {status}"))
            return outcomes

        if targets:
            for pid, status, msg in asyncio.run(_probe_all()):
                results.append(
                    CheckResult(
                        name=f"endpoint[{pid}]",
                        status=status,
                        message=msg,
                    )
                )
        return results

    def check_provider_loadable(
        self, providers: list[ProviderEntry]
    ) -> list[CheckResult]:
        """Verify each enabled provider's class can be instantiated."""
        reg = self._build_provider_registry()
        results: list[CheckResult] = []
        for entry in providers:
            if not entry.enabled:
                continue
            name = f"loadable[{entry.id}]"
            if reg.get_class(entry.id) is None:
                results.append(
                    CheckResult(
                        name=name,
                        status=CheckStatus.FAIL,
                        message="provider class not registered",
                    )
                )
                continue
            try:
                reg.instantiate(entry.id)
            except Exception as exc:
                results.append(
                    CheckResult(
                        name=name,
                        status=CheckStatus.FAIL,
                        message=f"instantiation failed: {exc}",
                    )
                )
                continue
            results.append(
                CheckResult(
                    name=name,
                    status=CheckStatus.OK,
                    message="instantiated",
                )
            )
        return results


def run_doctor(
    ssh_profile: str | None = None,
    systems: list[str] | None = None,
) -> DoctorReport:
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

    if systems:
        report.checks.extend(doctor.check_systems_config_names(systems))

    return report
