"""Tests for config loading and env var resolution."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multiscraper.config.loader import (
    load_config,
    load_config_yaml,
    load_systems_yaml,
    resolve_env_vars,
    resolve_path,
)
from multiscraper.config.models import (
    MultiscraperConfig,
    System,
    SystemsConfig,
    Transport,
    TransportsConfig,
)


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


def test_load_config_yaml_ssh(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARCADE_PASS", "secret123")
    yaml_content = """
transports:
  - name: arcade
    kind: ssh
    host: 192.168.1.28
    user: arcade
    password: ${env:ARCADE_PASS}
    base_path: /home/arcade/ROMs

current_transport: arcade

orchestrator:
  workers: 4
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_content)
    cfg = load_config_yaml(cfg_path)
    assert isinstance(cfg, TransportsConfig)
    assert cfg.current_transport == "arcade"
    assert cfg.transports[0].password == "secret123"
    assert cfg.orchestrator.workers == 4


def test_load_config_yaml_local(tmp_path: Path):
    yaml_content = """
transports:
  - name: workstation
    kind: local
    base_path: /home/user/roms

current_transport: workstation
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_content)
    cfg = load_config_yaml(cfg_path)
    assert cfg.current_transport == "workstation"
    assert cfg.transports[0].base_path == "/home/user/roms"


def test_load_config_yaml_invalid_fails(tmp_path: Path):
    yaml_content = """
transports: []
current_transport: nothing
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_content)
    with pytest.raises(ValidationError):
        load_config_yaml(cfg_path)


def test_load_systems_yaml_minimal(tmp_path: Path):
    yaml_content = """
systems:
  - name: snes
    relative_path: /snes
    extensions: [sfc, smc]
  - name: gba
    relative_path: /gba
    extensions: [gba]
"""
    systems_path = tmp_path / "systems.yaml"
    systems_path.write_text(yaml_content)
    cfg = load_systems_yaml(systems_path)
    assert isinstance(cfg, SystemsConfig)
    assert len(cfg.systems) == 2
    assert cfg.systems[0].relative_path == "/snes"


def test_load_systems_yaml_invalid_fails(tmp_path: Path):
    yaml_content = """
systems:
  - name: snes
    extensions: [sfc]
"""
    systems_path = tmp_path / "systems.yaml"
    systems_path.write_text(yaml_content)
    with pytest.raises(ValidationError):
        load_systems_yaml(systems_path)


def test_resolve_path_full_ignores_base():
    transport = Transport(name="a", kind="local", base_path="/home/arcade/ROMs")
    system = System(name="psx", full_path="/mnt/external/roms/psx", extensions=["cue"])
    assert resolve_path(transport, system) == "/mnt/external/roms/psx"


def test_resolve_path_relative_with_slash():
    transport = Transport(name="a", kind="local", base_path="/home/arcade/ROMs")
    system = System(name="snes", relative_path="/snes", extensions=["sfc"])
    assert resolve_path(transport, system) == "/home/arcade/ROMs/snes"


def test_resolve_path_relative_without_slash():
    transport = Transport(name="a", kind="local", base_path="/home/arcade/ROMs")
    system = System(name="snes", relative_path="snes", extensions=["sfc"])
    assert resolve_path(transport, system) == "/home/arcade/ROMs/snes"


def test_resolve_path_relative_normalizes_trailing_slash_on_base():
    transport = Transport(name="a", kind="local", base_path="/home/arcade/ROMs/")
    system = System(name="snes", relative_path="/snes", extensions=["sfc"])
    assert resolve_path(transport, system) == "/home/arcade/ROMs/snes"


def test_resolve_path_empty_base_with_relative():
    transport = Transport(name="a", kind="local", base_path="")
    system = System(name="snes", relative_path="/snes", extensions=["sfc"])
    assert resolve_path(transport, system) == "/snes"
