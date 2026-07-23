"""Tests for config loading and env var resolution."""

from pathlib import Path

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
