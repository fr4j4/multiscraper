"""Provider and Identifier Protocols for multiscraper.

Every data source implements the Provider Protocol. Identifier-only
sources (like Hasheous) implement the Identifier Protocol instead.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from multiscraper.models import Candidate, MediaRef, MediaType, Rom


class ProviderBlockedError(Exception):
    """Raised by a provider when it is rate-limited or otherwise blocked.

    The cascade catches this exception, marks the provider as
    blocked for ``cooldown_after_blocked_sec`` and continues with
    the next provider. If every media provider ends up blocked the
    cascade raises ``AllProvidersBlocked``.
    """

    def __init__(
        self, provider_name: str, retry_after: float | None = None,
        reason: str = "rate_limited",
    ) -> None:
        self.provider_name = provider_name
        self.retry_after = retry_after
        self.reason = reason
        super().__init__(
            f"provider {provider_name!r} blocked: {reason}"
            + (f" (retry after {retry_after}s)" if retry_after else ""),
        )


class AllProvidersBlocked(Exception):
    """Raised by the cascade when every media provider is blocked."""

    def __init__(self, blocked_providers: list[str]) -> None:
        self.blocked_providers = blocked_providers
        super().__init__(
            f"all providers blocked: {sorted(blocked_providers)}",
        )


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
