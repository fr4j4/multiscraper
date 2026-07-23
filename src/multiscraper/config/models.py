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
