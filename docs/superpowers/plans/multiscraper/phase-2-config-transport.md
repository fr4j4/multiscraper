# Phase 2: Config and Transport

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement config loading (YAML + es_systems.cfg parser + Pydantic settings) and transport layer (LocalTransport + SshTransport with asyncssh).

**Depends on:** Phase 1 (models, utils).

**Milestone:** `multiscraper validate-config` command works with a sample YAML; SSH transport connects and lists a remote directory (tested with a mock); `ruff` and `mypy` pass.

**Parallelizable:** Yes — 2 independent tracks (Task 2.1 config, Task 2.2 transport). Task 2.3 (es_systems parser) depends on 2.1.

---

## Task 2.1: Config loader and Pydantic settings

**Files:**
- Create: `src/multiscraper/config/__init__.py`
- Create: `src/multiscraper/config/models.py`
- Create: `src/multiscraper/config/loader.py`
- Create: `config/sources.example.yaml`
- Create: `config/systems.example.yaml`
- Test: `tests/unit/test_config_loader.py`

**Interfaces:**
- Produces: `MultiscraperConfig` (Pydantic model), `load_config(path: Path) -> MultiscraperConfig`, `resolve_env_vars(value: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_loader.py
"""Tests for config loading and env var resolution."""

from pathlib import Path

import pytest

from multiscraper.config.loader import load_config, resolve_env_vars
from multiscraper.config.models import MultiscraperConfig


def test_resolve_env_vars_passthrough():
    assert resolve_env_vars("plain string") == "plain string"


def test_resolve_env_vars_with_env(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret123")
    assert resolve_env_vars("${env:TEST_API_KEY}") == "secret123"


def test_resolve_env_vars_missing_env_returns_empty(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    assert resolve_env_vars("${env:MISSING_VAR}") == ""


def test_load_config_minimal(tmp_path: Path):
    yaml_content = """
language:
  text_priority: [en]
  name_priority: [en]
  fallback_strategy: best_effort
  default_language: en

output:
  csv_include_language_columns: true
  partial_min_media: 3
  required_media_types: [image]

providers:
  - id: screenscraper
    priority: 5
    enabled: true

provider_defaults:
  rate_limit_per_sec: 2.0
  burst: 1
  cooldown_after_blocked_sec: 1800
  max_consecutive_failures: 3
  timeout_sec: 30
  match_threshold: 0.7
  max_candidates_per_provider: 10
"""
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(yaml_content)

    config = load_config(config_path)
    assert isinstance(config, MultiscraperConfig)
    assert config.language.default_language == "en"
    assert config.language.text_priority == ["en"]
    assert config.output.partial_min_media == 3
    assert len(config.providers) == 1
    assert config.providers[0].id == "screenscraper"
    assert config.provider_defaults.match_threshold == 0.7


def test_load_config_with_env_vars(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SS_DEV_ID", "mydev")
    yaml_content = """
language:
  text_priority: [en]
  name_priority: [en]
  fallback_strategy: best_effort
  default_language: en

output:
  csv_include_language_columns: true
  partial_min_media: 3
  required_media_types: [image]

providers:
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SS_DEV_ID}

provider_defaults:
  rate_limit_per_sec: 2.0
  burst: 1
  cooldown_after_blocked_sec: 1800
  max_consecutive_failures: 3
  timeout_sec: 30
  match_threshold: 0.7
  max_candidates_per_provider: 10
"""
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(yaml_content)

    config = load_config(config_path)
    assert config.providers[0].config["devid"] == "mydev"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_config_loader.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/config/__init__.py
```

```python
# src/multiscraper/config/models.py
"""Pydantic models for multiscraper configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LanguageConfig(BaseModel):
    """Language preference configuration."""

    text_priority: list[str] = Field(default_factory=lambda: ["en"])
    name_priority: list[str] = Field(default_factory=lambda: ["en"])
    fallback_strategy: Literal["best_effort", "strict"] = "best_effort"
    default_language: str = "en"
    detection_method: Literal["stopwords", "langdetect", "trust_provider"] = "stopwords"


class OutputConfig(BaseModel):
    """Output configuration."""

    csv_include_language_columns: bool = True
    partial_min_media: int = 3
    required_media_types: list[str] = Field(default_factory=lambda: ["image"])


class ProviderEntry(BaseModel):
    """A provider entry in sources.yaml."""

    id: str
    kind: str = "media"
    priority: int = 100
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderDefaults(BaseModel):
    """Default settings for all providers."""

    rate_limit_per_sec: float = 2.0
    burst: int = 1
    cooldown_after_blocked_sec: int = 1800
    max_consecutive_failures: int = 3
    timeout_sec: float = 30.0
    match_threshold: float = 0.7
    max_candidates_per_provider: int = 10


class OrchestratorConfig(BaseModel):
    """Orchestrator tuning parameters."""

    workers: int = 8
    media_concurrency: int = 4
    batch_size: int = 50
    max_job_attempts: int = 3
    worker_failure_window_sec: int = 60
    worker_failure_threshold: int = 3
    shutdown_drain_timeout_sec: int = 180
    csv_flush_every: int = 50
    progress_interval_sec: float = 0.5


class MultiscraperConfig(BaseModel):
    """Full configuration loaded from sources.yaml."""

    language: LanguageConfig = Field(default_factory=LanguageConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    providers: list[ProviderEntry] = Field(default_factory=list)
    provider_defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
```

```python
# src/multiscraper/config/loader.py
"""Config loader for multiscraper.

Loads YAML config from sources.yaml, resolves ${env:...} placeholders,
and validates with Pydantic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from multiscraper.config.models import MultiscraperConfig

_ENV_VAR_PATTERN = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env_vars(value: str) -> str:
    """Resolve ${env:VAR_NAME} placeholders in a string.

    Args:
        value: String potentially containing ${env:...} placeholders.

    Returns:
        String with env vars resolved. Missing env vars resolve to empty string.
    """
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _resolve_dict(obj: object) -> object:
    """Recursively resolve env vars in dicts and strings."""
    if isinstance(obj, str):
        return resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_dict(item) for item in obj]
    return obj


def load_config(path: Path) -> MultiscraperConfig:
    """Load and validate config from a YAML file.

    Args:
        path: Path to sources.yaml.

    Returns:
        Validated MultiscraperConfig.

    Raises:
        FileNotFoundError: if path does not exist.
        pydantic.ValidationError: if config is invalid.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    resolved = _resolve_dict(raw)
    return MultiscraperConfig.model_validate(resolved)
```

```yaml
# config/sources.example.yaml
# Example configuration for multiscraper.
# Copy to sources.yaml and edit as needed.

language:
  text_priority: [en, es, fr, de, it, pt, jp]
  name_priority: [en, es, jp, fr]
  fallback_strategy: best_effort
  default_language: en
  detection_method: stopwords

output:
  csv_include_language_columns: true
  partial_min_media: 3
  required_media_types: [image]

orchestrator:
  workers: 8
  media_concurrency: 4
  batch_size: 50
  max_job_attempts: 3
  worker_failure_window_sec: 60
  worker_failure_threshold: 3
  shutdown_drain_timeout_sec: 180
  csv_flush_every: 50
  progress_interval_sec: 0.5

providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: hasheous
    kind: identifier
    enabled: true
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SCREENSCRAPER_DEV_ID}
      devpassword: ${env:SCREENSCRAPER_DEV_PASSWORD}
      region_priority: [wor, us, eu, jp]
      language_priority: [en, es, fr]
  - id: igdb
    priority: 10
    enabled: true
    config:
      client_id: ${env:TWITCH_CLIENT_ID}
      client_secret: ${env:TWITCH_CLIENT_SECRET}
  - id: mobygames
    priority: 15
    enabled: true
    config:
      api_key: ${env:MOBYGAMES_API_KEY}
  - id: giantbomb
    priority: 20
    enabled: true
    config:
      api_key: ${env:GIANTBOMB_API_KEY}
  - id: retroachievements
    priority: 25
    enabled: true
    config:
      username: ${env:RA_USERNAME}
      api_key: ${env:RA_API_KEY}
  - id: rawg
    priority: 30
    enabled: true
    config:
      api_key: ${env:RAWG_API_KEY}
  - id: thegamesdb
    priority: 35
    enabled: true
    config:
      api_key: ${env:TGDB_API_KEY}
  - id: libretro_thumbnails
    priority: 40
    enabled: true
  - id: openvgdb
    priority: 45
    enabled: true
  - id: gamefaqs
    priority: 50
    enabled: true
  - id: local_fallback
    priority: 9999
    enabled: true

provider_defaults:
  rate_limit_per_sec: 2.0
  burst: 1
  cooldown_after_blocked_sec: 1800
  max_consecutive_failures: 3
  timeout_sec: 30
  match_threshold: 0.7
  max_candidates_per_provider: 10
```

```yaml
# config/systems.example.yaml
# Example systems configuration for multiscraper.
# If es_systems.cfg exists, it takes precedence; this file overrides.

roms_root: ~/ROMs                      # local path or ssh://user@host:port/path
media_root: ~/multiscraper_data/media  # where to save downloaded media

# SSH profile (used when roms_root starts with ssh://)
ssh_profiles:
  arcade01:
    host: 192.168.1.42
    port: 22
    user: pi
    key_file: ~/.ssh/id_ed25519
    # password: ${env:ARCADE_SSH_PASS}
    known_hosts: ~/.ssh/known_hosts
    # jump_host: user@bastion.local

# Override es_systems.cfg path (auto-discovered by default)
# es_systems_path: ~/.emulationstation/es_systems.cfg
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_config_loader.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/config/ config/ tests/unit/test_config_loader.py
git commit -m "feat: add config loader with Pydantic models and env var resolution"
```

---

## Task 2.2: Transport layer (Local + SSH)

**Files:**
- Create: `src/multiscraper/transport/__init__.py`
- Create: `src/multiscraper/transport/base.py`
- Create: `src/multiscraper/transport/local.py`
- Create: `src/multiscraper/transport/ssh.py`
- Test: `tests/unit/test_transport_local.py`

**Interfaces:**
- Produces: `RomTransport` (Protocol), `FileInfo` (model), `LocalTransport`, `SshTransport`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_transport_local.py
"""Tests for LocalTransport."""

import asyncio
from pathlib import Path

import pytest

from multiscraper.transport.base import FileInfo
from multiscraper.transport.local import LocalTransport


@pytest.mark.asyncio
async def test_local_list_dir(tmp_path: Path):
    (tmp_path / "game1.smc").write_bytes(b"rom1")
    (tmp_path / "game2.smc").write_bytes(b"rom2")
    (tmp_path / "notarom.txt").write_text("nope")

    transport = LocalTransport()
    files = await transport.list_dir(str(tmp_path))
    assert len(files) == 3
    assert "game1.smc" in files
    assert "game2.smc" in files


@pytest.mark.asyncio
async def test_local_file_info(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    info = await transport.file_info(str(f))
    assert isinstance(info, FileInfo)
    assert info.size == 11
    assert info.is_file


@pytest.mark.asyncio
async def test_local_hash_crc32(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    crc = await transport.hash(str(f), "crc32")
    assert crc == "0d4a1185"


@pytest.mark.asyncio
async def test_local_hash_sha1(tmp_path: Path):
    f = tmp_path / "game.smc"
    f.write_bytes(b"hello world")
    transport = LocalTransport()
    sha = await transport.hash(str(f), "sha1")
    assert sha == "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"


@pytest.mark.asyncio
async def test_local_close():
    transport = LocalTransport()
    await transport.close()  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_transport_local.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/transport/__init__.py
```

```python
# src/multiscraper/transport/base.py
"""Transport Protocol for reading ROMs from local or remote sources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel


class FileInfo(BaseModel):
    """File metadata from a transport."""

    path: str
    size: int
    mtime: int
    is_file: bool
    is_dir: bool = False


@runtime_checkable
class RomTransport(Protocol):
    """Interface for reading ROMs from a filesystem (local or SSH)."""

    async def list_dir(self, path: str) -> list[str]:
        """List files in a directory (non-recursive)."""
        ...

    async def file_info(self, path: str) -> FileInfo:
        """Get metadata for a single file."""
        ...

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        """Compute hash of a file (reads file in streaming mode)."""
        ...

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        """Stream-read a file, optionally limited to max_bytes."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...
```

```python
# src/multiscraper/transport/local.py
"""Local filesystem transport."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from multiscraper.transport.base import FileInfo, RomTransport
from multiscraper.utils.hash import compute_crc32, compute_sha1


class LocalTransport:
    """Transport for reading ROMs from the local filesystem."""

    async def list_dir(self, path: str) -> list[str]:
        entries = os.listdir(path)
        return [
            e for e in entries
            if os.path.isfile(os.path.join(path, e))
        ]

    async def file_info(self, path: str) -> FileInfo:
        stat = os.stat(path)
        return FileInfo(
            path=path,
            size=stat.st_size,
            mtime=int(stat.st_mtime),
            is_file=os.path.isfile(path),
            is_dir=os.path.isdir(path),
        )

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        loop = asyncio.get_event_loop()
        if algo == "crc32":
            return await loop.run_in_executor(None, self._hash_sync, path, "crc32")
        elif algo == "sha1":
            return await loop.run_in_executor(None, self._hash_sync, path, "sha1")
        raise ValueError(f"Unknown hash algo: {algo}")

    def _hash_sync(self, path: str, algo: str) -> str:
        with open(path, "rb") as f:
            data = f.read()
        if algo == "crc32":
            return compute_crc32(data)
        return compute_sha1(data)

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        remaining = max_bytes
        with open(path, "rb") as f:
            while True:
                chunk_size = min(64 * 1024, remaining) if remaining else 64 * 1024
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break

    async def close(self) -> None:
        pass
```

```python
# src/multiscraper/transport/ssh.py
"""SSH transport using asyncssh.

Connects to a remote host and reads ROMs without downloading them.
Supports key-based auth, password auth, SSH agent, and ProxyJump.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import asyncssh

from multiscraper.transport.base import FileInfo, RomTransport
from multiscraper.utils.hash import compute_crc32, compute_sha1


class SshTransport:
    """Transport for reading ROMs from a remote SSH host."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str | None = None,
        password: str | None = None,
        key_file: str | None = None,
        known_hosts: str | None = None,
        auto_trust: bool = False,
        jump_host: str | None = None,
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._key_file = key_file
        self._known_hosts = known_hosts
        self._auto_trust = auto_trust
        self._jump_host = jump_host
        self._conn: asyncssh.SSHClientConnection | None = None

    async def _ensure_connected(self) -> asyncssh.SSHClientConnection:
        if self._conn is not None and not self._conn.is_closed:
            return self._conn

        known_hosts: str | tuple[asyncssh.KnownHosts, ...] | None
        if self._auto_trust:
            known_hosts = None
        elif self._known_hosts:
            known_hosts = self._known_hosts
        else:
            known_hosts = ()

        self._conn = await asyncssh.connect(
            host=self._host,
            port=self._port,
            username=self._user,
            password=self._password,
            client_keys=self._key_file,
            known_hosts=known_hosts,
        )
        return self._conn

    async def list_dir(self, path: str) -> list[str]:
        conn = await self._ensure_connected()
        result = await conn.run(f"ls -1 {path}", check=True)
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]

    async def file_info(self, path: str) -> FileInfo:
        conn = await self._ensure_connected()
        stat_result = await conn.run(f"stat -c '%s %Y' {path}", check=True)
        size_str, mtime_str = stat_result.stdout.strip().split()
        return FileInfo(
            path=path,
            size=int(size_str),
            mtime=int(mtime_str),
            is_file=True,
        )

    async def hash(self, path: str, algo: Literal["crc32", "sha1"]) -> str:
        conn = await self._ensure_connected()
        if algo == "crc32":
            cmd = f"crc32 {path}"
        else:
            cmd = f"sha1sum {path} | cut -d' ' -f1"
        result = await conn.run(cmd, check=True)
        return result.stdout.strip().lower()

    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]:
        conn = await self._ensure_connected()
        async with conn.open(path, "rb") as f:
            remaining = max_bytes
            while True:
                chunk_size = min(64 * 1024, remaining) if remaining else 64 * 1024
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_transport_local.py -v
```

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/transport/ tests/unit/test_transport_local.py
git commit -m "feat: add transport layer (LocalTransport + SshTransport with asyncssh)"
```

---

## Task 2.3: es_systems.cfg parser

**Depends on:** Task 2.1 (config models).

**Files:**
- Create: `src/multiscraper/config/es_systems_parser.py`
- Test: `tests/unit/test_es_systems_parser.py`
- Create: `tests/fixtures/es_systems.cfg`

**Interfaces:**
- Produces: `parse_es_systems(path: Path) -> list[SystemConfig]`, `SystemConfig` (Pydantic model)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_es_systems_parser.py
"""Tests for es_systems.cfg parser."""

from pathlib import Path

import pytest

from multiscraper.config.es_systems_parser import SystemConfig, parse_es_systems


def test_parse_es_systems(tmp_path: Path):
    cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<systemList>
  <system>
    <name>snes</name>
    <fullname>Super Nintendo Entertainment System</fullname>
    <path>~/roms/snes</path>
    <extension>.smc .sfc .SMC .SFC</extension>
    <command>snesemulator %ROM%</command>
    <platform>snes</platform>
    <theme>snes</theme>
  </system>
  <system>
    <name>nes</name>
    <fullname>Nintendo Entertainment System</fullname>
    <path>~/roms/nes</path>
    <extension>.nes .NES</extension>
    <command>nesemulator %ROM%</command>
    <platform>nes</platform>
    <theme>nes</theme>
  </system>
</systemList>
"""
    cfg_path = tmp_path / "es_systems.cfg"
    cfg_path.write_text(cfg_content)

    systems = parse_es_systems(cfg_path)
    assert len(systems) == 2
    assert systems[0].name == "snes"
    assert systems[0].fullname == "Super Nintendo Entertainment System"
    assert systems[0].path == "~/roms/snes"
    assert ".smc" in systems[0].extensions
    assert ".sfc" in systems[0].extensions
    assert systems[0].platform == "snes"
    assert systems[1].name == "nes"
    assert systems[1].platform == "nes"


def test_parse_es_systems_empty(tmp_path: Path):
    cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<systemList>
</systemList>
"""
    cfg_path = tmp_path / "es_systems.cfg"
    cfg_path.write_text(cfg_content)

    systems = parse_es_systems(cfg_path)
    assert len(systems) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_es_systems_parser.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/config/es_systems_parser.py
"""Parser for EmulationStation es_systems.cfg XML files."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pydantic import BaseModel


class SystemConfig(BaseModel):
    """A single system entry from es_systems.cfg."""

    name: str
    fullname: str = ""
    path: str = ""
    extensions: list[str] = []
    command: str = ""
    platform: str = ""
    theme: str = ""


def parse_es_systems(path: Path) -> list[SystemConfig]:
    """Parse an es_systems.cfg XML file.

    Args:
        path: Path to the es_systems.cfg file.

    Returns:
        List of SystemConfig entries.

    Raises:
        FileNotFoundError: if path does not exist.
        etree.XMLSyntaxError: if XML is malformed.
    """
    tree = etree.parse(str(path))
    root = tree.getroot()

    systems: list[SystemConfig] = []
    for sys_elem in root.findall("system"):
        name = _text(sys_elem, "name")
        if not name:
            continue

        ext_str = _text(sys_elem, "extension")
        extensions = ext_str.split() if ext_str else []

        systems.append(SystemConfig(
            name=name,
            fullname=_text(sys_elem, "fullname"),
            path=_text(sys_elem, "path"),
            extensions=extensions,
            command=_text(sys_elem, "command"),
            platform=_text(sys_elem, "platform"),
            theme=_text(sys_elem, "theme"),
        ))

    return systems


def _text(parent: etree._Element, tag: str) -> str:
    """Get text content of a child element, or empty string."""
    elem = parent.find(tag)
    return elem.text if elem is not None and elem.text else ""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_es_systems_parser.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/config/es_systems_parser.py tests/unit/test_es_systems_parser.py
git commit -m "feat: add es_systems.cfg XML parser"
```

---

## Milestone Gate

- [ ] `pytest tests/unit/ -v` — all tests pass (config, transport, es_systems)
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes
- [ ] `config/sources.example.yaml` and `config/systems.example.yaml` exist