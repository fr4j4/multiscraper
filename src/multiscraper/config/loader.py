"""Config loader for multiscraper.

Loads three YAML files (config.yaml, systems.yaml, sources.yaml),
resolves ${env:...} placeholders, and validates each with Pydantic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from multiscraper.config.models import (
    MultiscraperConfig,
    System,
    SystemsConfig,
    Transport,
    TransportsConfig,
)

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
    """Load and validate sources.yaml.

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


def load_config_yaml(path: Path) -> TransportsConfig:
    """Load and validate config.yaml (transports + orchestrator)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    resolved = _resolve_dict(raw)
    return TransportsConfig.model_validate(resolved)


def load_systems_yaml(path: Path) -> SystemsConfig:
    """Load and validate systems.yaml."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    resolved = _resolve_dict(raw)
    return SystemsConfig.model_validate(resolved)


def resolve_path(transport: Transport, system: System) -> str:
    """Resolve a system path against the transport's base_path.

    - `full_path` is returned as-is, ignoring `base_path`.
    - `relative_path` is appended to `base_path` with exactly one `/`
      separator, even if the relative path already has a leading `/`
      or the base has a trailing `/`.
    - If `relative_path` is empty/falsy and `full_path` is also None,
      the base is returned.
    """
    if system.full_path is not None:
        return system.full_path
    base = transport.base_path.rstrip("/")
    rel = system.relative_path or ""
    if not rel:
        return base
    if not rel.startswith("/"):
        rel = "/" + rel
    return base + rel
