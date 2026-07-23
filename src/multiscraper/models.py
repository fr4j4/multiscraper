"""Core Pydantic models for multiscraper.

These models are the single source of truth for in-memory representation
of ROMs, candidates, scraped results, and run reports. They are JSON-
serializable for SQLite persistence via model_dump_json / model_validate_json.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class MediaType(StrEnum):
    """Types of media that can be scraped for a game."""

    IMAGE = "image"
    THUMBNAIL = "thumbnail"
    VIDEO = "video"
    MARQUEE = "marquee"
    BOX3D = "box3d"
    BACKCOVER = "backcover"
    FANART = "fanart"
    MANUAL = "manual"
    MIXIMAGE = "miximage"
    LOGO = "logo"


class ScrapeStatus(StrEnum):
    """Final status of a scrape operation for a single ROM."""

    OK = "OK"
    PARTIAL = "PARTIAL"
    NO_MATCH = "NO_MATCH"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"


class IdentifyMethod(StrEnum):
    """Method used to identify a ROM."""

    CRC32 = "crc32"
    SHA1 = "sha1"
    NAME_ONLY = "name_only"
    HASHEOUS = "hasheous"


class RomIdentifier(BaseModel):
    """What the RomTransport can calculate about a ROM without downloading it."""

    rel_path: str
    size: int
    mtime: int
    crc32: str | None = None
    sha1: str | None = None
    cache_key: str


class Rom(BaseModel):
    """A discovered ROM, normalized and ready for scraping."""

    system: str
    rom_id: RomIdentifier
    raw_name: str
    normalized_name: str
    preferred_region: str = "wor"
    preferred_language: str = "en"


class MediaRef(BaseModel):
    """A reference to a media returned by a provider (URL + metadata)."""

    type: MediaType
    url: HttpUrl
    ext: str
    region: str | None = None
    size_bytes: int | None = None
    source: str


class Candidate(BaseModel):
    """A game candidate returned by a provider before choosing the best."""

    provider: str
    source_id: str
    name: str
    match_score: float = Field(ge=0.0, le=1.0)
    releasedate: datetime | None = None
    developer: str | None = None
    publisher: str | None = None
    genre: str | None = None
    players: int | None = None
    rating: float | None = None
    description: str | None = None
    media: list[MediaRef] = []


class GameMetadata(BaseModel):
    """Subset of metadata that goes into the <game> tag of gamelist.xml."""

    name: str
    desc: str | None = None
    rating: float | None = None
    releasedate: datetime | None = None
    developer: str | None = None
    publisher: str | None = None
    genre: str | None = None
    players: int | None = None
    sortname: str | None = None


class MediaFile(BaseModel):
    """A media file already downloaded and persisted to disk."""

    type: MediaType
    local_path: str
    ext: str
    bytes: int
    sha256: str
    source: str


class ScrapedResult(BaseModel):
    """Final result of processing a ROM. Persisted as-is in SQLite."""

    rom: Rom
    status: ScrapeStatus
    identify_method: IdentifyMethod
    chosen_provider: str | None = None
    match_score: float | None = None
    metadata: GameMetadata | None = None
    media: list[MediaFile] = []
    warnings: list[str] = []
    error: str | None = None
    elapsed_ms: int = 0
    fetched_at: datetime


class RunTotals(BaseModel):
    """Aggregated totals for a run, persisted in summary.json."""

    roms_total: int = 0
    roms_ok: int = 0
    roms_partial: int = 0
    roms_no_match: int = 0
    roms_blocked: int = 0
    roms_error: int = 0
    roms_timed_out: int = 0
    roms_skipped: int = 0
    media_files_downloaded: int = 0
    media_bytes_total: int = 0
    identify_method_counts: dict[IdentifyMethod, int] = {}
    providers_used: dict[str, int] = {}
    error_breakdown: dict[str, int] = {}
    by_status: dict[ScrapeStatus, int] = {}
    by_provider_match: dict[str, int] = {}
    avg_match_score: float = 0.0
    p50_match_score: float = 0.0
    p95_match_score: float = 0.0
    avg_elapsed_ms_per_rom: int = 0
    throughput_roms_per_min: float = 0.0
    throughput_mb_per_min: float = 0.0


class RunReport(BaseModel):
    """Full report for a run."""

    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    config_snapshot: dict[str, object]
    totals: RunTotals = RunTotals()
    status: Literal["running", "ok", "partial", "paused", "aborted", "error"] = "running"
