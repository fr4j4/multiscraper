"""Provider and Identifier Protocols for multiscraper.

Every data source implements the Provider Protocol. Identifier-only
sources (like Hasheous) implement the Identifier Protocol instead.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from multiscraper.models import Candidate, MediaRef, MediaType, Rom


@runtime_checkable
class Provider(Protocol):
    """Interface for every media/data provider."""

    name: str
    requires_auth: bool
    auth_fields: list[str]
    rate_limit_per_sec: float
    priority: int
    supported_media: set[MediaType]
    platform_map: dict[str, str | int]
    is_identifier_only: bool
    is_offline: bool
    health_url: str | None

    async def setup(self, config: dict[str, object]) -> None: ...
    async def close(self) -> None: ...
    async def search(self, rom: Rom) -> list[Candidate]: ...
    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]: ...
    def detect_blocked(self, response: object, body: bytes) -> bool: ...
    def is_auth_missing(self, exc: Exception) -> bool: ...


class IdentifierResult(BaseModel):
    """Result from an identifier provider (hash → name lookup)."""

    canonical_name: str
    platform: str
    source_id: str
    provider: str
    confidence: float = 1.0


@runtime_checkable
class Identifier(Protocol):
    """Interface for identifier-only providers (hash resolvers)."""

    name: str

    async def identify(self, rom: Rom) -> IdentifierResult | None: ...
