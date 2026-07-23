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

if TYPE_CHECKING:
    from multiscraper.config.models import (
        ProviderEntry,
        System,
        SystemsConfig,
        Transport,
        TransportsConfig,
    )
    from multiscraper.transport.local import LocalTransport
    from multiscraper.transport.ssh import SshTransport


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
        from multiscraper.config.loader import load_systems_yaml

        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return CheckResult(
                name="systems_config",
                status=CheckStatus.WARN,
                message=f"{path} not found (will auto-discover es_systems.cfg)",
            )
        try:
            load_systems_yaml(path)
        except Exception as exc:
            return CheckResult(
                name="systems_config",
                status=CheckStatus.FAIL,
                message=f"invalid: {exc}",
            )
        return CheckResult(
            name="systems_config",
            status=CheckStatus.OK,
            message=f"{path} present",
        )

    def check_transports_config(
        self, config_path: Path | None = None
    ) -> CheckResult:
        from multiscraper.config.loader import load_config_yaml

        path = config_path or Path("config/config.yaml")
        if not path.exists():
            return CheckResult(
                name="transports_config",
                status=CheckStatus.FAIL,
                message=f"{path} not found",
            )
        try:
            load_config_yaml(path)
        except Exception as exc:
            return CheckResult(
                name="transports_config",
                status=CheckStatus.FAIL,
                message=f"invalid: {exc}",
            )
        return CheckResult(
            name="transports_config",
            status=CheckStatus.OK,
            message=f"{path} present",
        )

    _SYSTEM_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
    _EXT_PATTERN = re.compile(r"^\.?[a-z0-9]{1,8}$")

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

    def _load_transports_config(
        self, config_path: Path | None = None
    ) -> TransportsConfig | None:
        from multiscraper.config.loader import load_config_yaml

        path = config_path or Path("config/config.yaml")
        if not path.exists():
            return None
        try:
            return load_config_yaml(path)
        except Exception:
            return None

    def _load_systems_config(
        self, config_path: Path | None = None
    ) -> SystemsConfig | None:
        from multiscraper.config.loader import load_systems_yaml

        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return None
        try:
            return load_systems_yaml(path)
        except Exception:
            return None

    def _load_systems_raw(
        self, config_path: Path | None = None
    ) -> list[dict[str, object]]:
        from typing import cast

        import yaml

        path = config_path or Path("config/systems.yaml")
        if not path.exists():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, dict):
            return []
        systems_obj = raw.get("systems", [])
        systems_list = cast(list[dict[str, object]], systems_obj) if isinstance(
            systems_obj, list
        ) else []
        return [s for s in systems_list if isinstance(s, dict)]

    def _validate_system_defensively(
        self, raw_entry: dict[str, object]
    ) -> tuple[System | None, str | None]:
        """Try to construct a System model from a raw dict.

        Returns (system, None) on success or (None, error_message) on
        failure. This is the defensive check called from
        `check_systems_config_names`; Pydantic normally catches
        schema problems at load time, but if it slips through, the
        doctor still surfaces a clear error.
        """
        from multiscraper.config.models import System

        try:
            return System.model_validate(raw_entry), None
        except Exception as exc:
            return None, str(exc)

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

    def check_systems_config_names(
        self, names: list[str]
    ) -> list[CheckResult]:
        """Validate system configuration for the given system names.

        Looks up each name in both es_systems.cfg (auto-discovered) and
        systems.yaml. The path is resolved against the current
        transport in config.yaml and checked for accessibility.
        """
        return asyncio.run(self._check_systems_config_names_async(names))

    async def _check_systems_config_names_async(
        self, names: list[str]
    ) -> list[CheckResult]:
        results: list[CheckResult] = []
        if not names:
            return results
        es_index = self._load_es_systems_index()
        systems_cfg = self._load_systems_config()
        raw_systems = self._load_systems_raw()
        current_transport: Transport | None = None
        transports_cfg = self._load_transports_config()
        if transports_cfg is not None:
            for t in transports_cfg.transports:
                if t.name == transports_cfg.current_transport:
                    current_transport = t
                    break
        transport_instance = self._build_transport_instance(current_transport)
        yaml_systems: dict[str, System] = (
            {s.name: s for s in systems_cfg.systems}
            if systems_cfg is not None
            else {}
        )
        yaml_raw_by_name: dict[str, dict[str, object]] = {
            str(s.get("name")): s
            for s in raw_systems
            if isinstance(s.get("name"), str)
        }
        for raw_name in names:
            name = str(raw_name)
            es_entry = es_index.get(name)
            yaml_entry: System | None = yaml_systems.get(name)
            parts: list[str] = []
            status = CheckStatus.OK
            if es_entry is None and yaml_entry is None and name not in yaml_raw_by_name:
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
            if yaml_entry is not None or name in yaml_raw_by_name:
                sources.append("systems.yaml")
            parts.append(f"source={'+'.join(sources)}")
            if es_entry is not None and yaml_entry is None and name not in yaml_raw_by_name:
                parts.append("no override in systems.yaml")
                if status == CheckStatus.OK:
                    status = CheckStatus.WARN
            if not self._validate_system_name(name):
                parts.append(f"name='{name}' (invalid format)")
                status = CheckStatus.FAIL
            if name in yaml_raw_by_name and yaml_entry is None:
                _valid, err = self._validate_system_defensively(yaml_raw_by_name[name])
                if err is not None:
                    parts.append(f"schema: {err}")
                    status = CheckStatus.FAIL
                    results.append(
                        CheckResult(
                            name=f"system[{name}]",
                            status=status,
                            message=", ".join(parts),
                        )
                    )
                    continue
            ext_value: object = []
            has_yaml_exts = False
            if yaml_entry is not None:
                ext_value = yaml_entry.extensions
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
            path_status, path_msg = await self._resolve_system_path(
                yaml_entry=yaml_entry,
                es_entry=es_entry,
                current_transport=current_transport,
                raw_entry=yaml_raw_by_name.get(name),
                transport_instance=transport_instance,
            )
            parts.append(path_msg)
            if path_status == CheckStatus.FAIL:
                status = CheckStatus.FAIL
            results.append(
                CheckResult(
                    name=f"system[{name}]",
                    status=status,
                    message=", ".join(parts),
                )
            )
        return results

    def _build_transport_instance(
        self, current_transport: Transport | None
    ) -> LocalTransport | SshTransport | None:
        """Build a RomTransport instance for the current transport config.

        Returns None if no current transport is set or the kind is unknown.
        """
        if current_transport is None:
            return None
        if current_transport.kind == "local":
            from multiscraper.transport.local import LocalTransport

            return LocalTransport()
        if current_transport.kind == "ssh":
            from multiscraper.transport.ssh import SshTransport

            return SshTransport(
                host=current_transport.host or "",
                port=current_transport.port,
                user=current_transport.user,
                password=current_transport.password,
                key_file=current_transport.key_file,
                known_hosts=current_transport.known_hosts,
                auto_trust=current_transport.auto_trust,
            )
        return None

    async def _resolve_system_path(
        self,
        yaml_entry: System | None,
        es_entry: tuple[str, list[str]] | None,
        current_transport: Transport | None,
        raw_entry: dict[str, object] | None = None,
        transport_instance: object | None = None,
    ) -> tuple[CheckStatus, str]:
        """Resolve and check a system's filesystem path.

        YAML systems have explicit relative_path/full_path. es_systems
        entries have an absolute path. If we can't resolve, report
        FAIL with the reason.
        """
        from multiscraper.config.loader import resolve_path

        if yaml_entry is not None:
            if current_transport is None:
                return (
                    CheckStatus.FAIL,
                    "path: no current_transport in config.yaml",
                )
            try:
                resolved = resolve_path(current_transport, yaml_entry)
            except Exception as exc:
                return CheckStatus.FAIL, f"path: {exc}"
            return await self._check_path_access(resolved, current_transport, transport_instance)
        if es_entry is not None:
            return await self._check_path_access(es_entry[0], current_transport, transport_instance)
        if raw_entry is not None and current_transport is not None:
            rel = raw_entry.get("relative_path")
            full = raw_entry.get("full_path")
            if isinstance(full, str) and full:
                return await self._check_path_access(
                    full, current_transport, transport_instance
                )
            if isinstance(rel, str) and rel:
                base = current_transport.base_path.rstrip("/")
                if not rel.startswith("/"):
                    rel = "/" + rel
                return await self._check_path_access(
                    base + rel, current_transport, transport_instance
                )
        return CheckStatus.FAIL, "path: unknown"

    async def _check_path_access(
        self,
        path: str,
        current_transport: Transport | None,
        transport_instance: object | None = None,
    ) -> tuple[CheckStatus, str]:
        if current_transport is None:
            if Path(path).is_dir():
                return CheckStatus.OK, f"path: {path}"
            return CheckStatus.FAIL, f"path: {path} not found"
        kind = current_transport.kind
        if transport_instance is None:
            return (
                CheckStatus.FAIL,
                f"path: {path} NOT FOUND on {current_transport.name} (transport unavailable)",
            )
        try:
            exists = bool(await transport_instance.path_exists(path))  # type: ignore[attr-defined]
        except Exception as exc:
            return (
                CheckStatus.FAIL,
                f"path: {path} NOT FOUND on {current_transport.name} ({kind}) ({exc})",
            )
        if exists:
            return CheckStatus.OK, f"path: {path} exists on {current_transport.name} ({kind})"
        return (
            CheckStatus.FAIL,
            f"path: {path} NOT FOUND on {current_transport.name} ({kind})",
        )

    def check_transports(
        self, transports: list[Transport]
    ) -> list[CheckResult]:
        """Test reachability of each transport."""
        results: list[CheckResult] = []
        for t in transports:
            name = f"transport[{t.name}]"
            if t.kind == "local":
                if Path(t.base_path).exists():
                    results.append(
                        CheckResult(
                            name=name,
                            status=CheckStatus.OK,
                            message=f"{t.base_path} exists",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            name=name,
                            status=CheckStatus.FAIL,
                            message=f"{t.base_path} not found",
                        )
                    )
                continue
            try:
                from multiscraper.transport.ssh import SshTransport

                transport = SshTransport(
                    host=t.host or "",
                    port=t.port,
                    user=t.user,
                    password=t.password,
                    key_file=t.key_file,
                    known_hosts=t.known_hosts,
                    auto_trust=t.auto_trust,
                )
                asyncio.run(transport._ensure_connected())
                results.append(
                    CheckResult(
                        name=name,
                        status=CheckStatus.OK,
                        message=f"{t.user}@{t.host} reachable",
                    )
                )
            except Exception as exc:
                results.append(
                    CheckResult(
                        name=name,
                        status=CheckStatus.FAIL,
                        message=f"{exc}",
                    )
                )
        return results

    def check_current_transport(self, config: TransportsConfig) -> CheckResult:
        """Validate that current_transport is set and references a real transport."""
        if not config.current_transport:
            return CheckResult(
                name="current_transport",
                status=CheckStatus.FAIL,
                message="current_transport is not set",
            )
        names = [t.name for t in config.transports]
        if config.current_transport not in names:
            return CheckResult(
                name="current_transport",
                status=CheckStatus.FAIL,
                message=(
                    f"current_transport '{config.current_transport}' "
                    f"not in transports: {names}"
                ),
            )
        return CheckResult(
            name="current_transport",
            status=CheckStatus.OK,
            message=f"current_transport={config.current_transport}",
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
    report.checks.append(doctor.check_transports_config())
    report.checks.append(doctor.check_sources_config())
    report.checks.append(doctor.check_systems_config())
    report.checks.append(doctor.check_es_systems())
    report.checks.append(doctor.check_disk_space())

    try:
        from multiscraper.config.loader import load_config, load_config_yaml

        cfg = load_config(Path("config/sources.yaml"))
        report.checks.append(doctor.check_provider_credentials(cfg.providers))
    except Exception:
        pass

    try:
        transports_cfg = load_config_yaml(Path("config/config.yaml"))
        report.checks.append(doctor.check_current_transport(transports_cfg))
        report.checks.extend(doctor.check_transports(transports_cfg.transports))
        if ssh_profile:
            for t in transports_cfg.transports:
                if t.name == ssh_profile:
                    report.checks.extend(doctor.check_transports([t]))
                    break
    except Exception:
        pass

    if systems:
        report.checks.extend(doctor.check_systems_config_names(systems))

    return report
