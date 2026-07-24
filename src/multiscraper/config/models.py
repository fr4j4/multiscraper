"""Pydantic models for multiscraper configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    discovery_concurrency_ssh: int = 8
    discovery_concurrency_local: int = 32
    discovery_poll_interval_sec: float = 0.5


class MultiscraperConfig(BaseModel):
    """Configuration loaded from sources.yaml.

    Sources.yaml is for provider cascade, language, output, and
    provider defaults only. Transports, systems, and orchestrator
    tunables live in config.yaml and systems.yaml.
    """

    language: LanguageConfig = Field(default_factory=LanguageConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    providers: list[ProviderEntry] = Field(default_factory=list)
    provider_defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)


class Transport(BaseModel):
    """A single transport declaration (local or SSH).

    `base_path` is the mandatory root directory the transport reads
    from. Systems reference this base via `relative_path` or use
    `full_path` to override per-system.
    """

    name: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    kind: Literal["ssh", "local"]
    base_path: str
    host: str | None = None
    port: int = 22
    user: str | None = None
    password: str | None = None
    key_file: str | None = None
    known_hosts: str | None = None
    auto_trust: bool = False

    @model_validator(mode="after")
    def _check_ssh_required_fields(self) -> Transport:
        if self.kind == "ssh":
            if not self.host:
                raise ValueError(
                    f"transport '{self.name}': host is required for kind=ssh"
                )
            if not self.user:
                raise ValueError(
                    f"transport '{self.name}': user is required for kind=ssh"
                )
        return self


class TransportsConfig(BaseModel):
    """Configuration loaded from config.yaml.

    Declares transports, the currently active transport, default
    filesystem paths, and orchestrator tunables.
    """

    transports: list[Transport] = Field(default_factory=list)
    current_transport: str
    defaults: dict[str, Any] = Field(default_factory=dict)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)

    @model_validator(mode="after")
    def _check_current_transport(self) -> TransportsConfig:
        if not self.transports:
            raise ValueError("transports: list cannot be empty")
        names = [t.name for t in self.transports]
        if len(names) != len(set(names)):
            raise ValueError("transports: names must be unique")
        if self.current_transport not in names:
            raise ValueError(
                f"current_transport '{self.current_transport}' not in transports: {names}"
            )
        return self


class System(BaseModel):
    """A single emulated system declared in systems.yaml.

    Each system has exactly one of `relative_path` (concatenated with
    the current transport's `base_path`) or `full_path` (used as-is).
    """

    name: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    relative_path: str | None = None
    full_path: str | None = None
    extensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_exactly_one_path(self) -> System:
        if self.relative_path is not None and self.full_path is not None:
            raise ValueError(
                f"system '{self.name}': only one of relative_path or full_path allowed"
            )
        if self.relative_path is None and self.full_path is None:
            raise ValueError(
                f"system '{self.name}': must have relative_path or full_path"
            )
        if self.relative_path is not None and self.relative_path == "":
            raise ValueError(f"system '{self.name}': relative_path cannot be empty")
        if self.full_path is not None and self.full_path == "":
            raise ValueError(f"system '{self.name}': full_path cannot be empty")
        return self


class SystemsConfig(BaseModel):
    """Configuration loaded from systems.yaml."""

    systems: list[System] = Field(default_factory=list)
