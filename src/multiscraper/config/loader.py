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
