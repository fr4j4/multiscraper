"""Tests for cascade logic with FakeProvider."""

import logging

import pytest
from pydantic import HttpUrl

from multiscraper.models import (
    Candidate,
    MediaRef,
    MediaType,
    Rom,
    RomIdentifier,
    ScrapeStatus,
)
from multiscraper.providers.base import (
    AllProvidersBlocked,  # noqa: F401
    IdentifierResult,  # noqa: F401
    ProviderBlockedError,  # noqa: F401
)
from multiscraper.providers.cascade import CascadeResult, run_cascade  # noqa: F401
from multiscraper.providers.registry import ProviderRegistry


class FakeGoodProvider:
    """A provider that returns a high-quality match."""

    name = "good_provider"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 10.0
    priority = 1
    supported_media: set[MediaType] = {MediaType.IMAGE}  # noqa: RUF012
    platform_map: dict[str, str | int] = {"snes": 4}  # noqa: RUF012
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return [
            Candidate(
                provider="good_provider",
                source_id="1",
                name=rom.normalized_name,
                match_score=0.95,
                description="A great game.",
            )
        ]

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        return {
            MediaType.IMAGE: MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl("https://example.com/img.jpg"),
                ext="jpg",
                source="good_provider",
            )
        }

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


class FakeBadProvider:
    """A provider that returns a low-quality match."""

    name = "bad_provider"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 10.0
    priority = 10
    supported_media: set[MediaType] = {MediaType.IMAGE}  # noqa: RUF012
    platform_map: dict[str, str | int] = {"snes": 4}  # noqa: RUF012
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return [
            Candidate(
                provider="bad_provider",
                source_id="2",
                name="Wrong Game",
                match_score=0.3,
            )
        ]

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc",
        size=1024,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_cascade_picks_best_provider() -> None:
    reg = ProviderRegistry()
    reg.register(FakeBadProvider())
    reg.register(FakeGoodProvider())

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers=set(),
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.OK
    assert result.chosen_provider == "good_provider"
    assert result.match_score == 0.95


@pytest.mark.asyncio
async def test_cascade_no_match() -> None:
    reg = ProviderRegistry()
    reg.register(FakeBadProvider())

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers=set(),
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.NO_MATCH


@pytest.mark.asyncio
async def test_cascade_raises_when_all_blocked() -> None:
    """When the only media provider is in blocked_providers, raise."""
    reg = ProviderRegistry()
    reg.register(FakeGoodProvider())

    with pytest.raises(AllProvidersBlocked) as exc_info:
        await run_cascade(
            rom=_make_rom(),
            registry=reg,
            match_threshold=0.7,
            blocked_providers={"good_provider"},
            wanted_media={MediaType.IMAGE},
        )
    assert exc_info.value.blocked_providers == ["good_provider"]


@pytest.mark.asyncio
async def test_cascade_skips_blocked_provider_falls_through() -> None:
    """A blocked provider is skipped, the next one is tried."""
    reg = ProviderRegistry()
    reg.register(FakeGoodProvider())  # priority=1, blocked
    reg.register(FakeBadProvider())   # priority=10, returns 0.3 < 0.7

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers={"good_provider"},
        wanted_media={MediaType.IMAGE},
    )
    # bad_provider was tried (its 0.3 score is below threshold)
    # so the cascade returns NO_MATCH.
    assert result.status == ScrapeStatus.NO_MATCH
    assert result.chosen_provider is None  # below threshold, not used


class _RaisingSearchProvider:
    """Provider whose search raises an exception."""

    name = "raising_provider"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 10.0
    priority = 1
    supported_media: set[MediaType] = set()  # noqa: RUF012
    platform_map: dict[str, str | int] = {"snes": 4}  # noqa: RUF012
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        raise RuntimeError("upstream timeout")

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


class _RaisingFetchMediaProvider(FakeGoodProvider):
    """Provider whose fetch_media raises an exception."""

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        raise RuntimeError("media fetch failed")


class _EmptyProvider:
    """Provider that returns no candidates."""

    name = "empty_provider"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 10.0
    priority = 1
    supported_media: set[MediaType] = set()  # noqa: RUF012
    platform_map: dict[str, str | int] = {"snes": 4}  # noqa: RUF012
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return []

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


@pytest.mark.asyncio
async def test_cascade_logs_provider_search_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a provider raises in search, the cascade should log a warning."""
    reg = ProviderRegistry()
    reg.register(_RaisingSearchProvider())

    with caplog.at_level(logging.WARNING, logger="multiscraper.providers.cascade"):
        await run_cascade(
            rom=_make_rom(),
            registry=reg,
            match_threshold=0.7,
            blocked_providers=set(),
            wanted_media={MediaType.IMAGE},
        )
    assert any(
        "cascade_provider_search_failed" in r.message
        and "raising_provider" in r.message
        for r in caplog.records
    ), f"expected warning, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_cascade_logs_fetch_media_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a provider raises in fetch_media, the cascade should log a warning."""
    reg = ProviderRegistry()
    reg.register(_RaisingFetchMediaProvider())

    with caplog.at_level(logging.WARNING, logger="multiscraper.providers.cascade"):
        await run_cascade(
            rom=_make_rom(),
            registry=reg,
            match_threshold=0.7,
            blocked_providers=set(),
            wanted_media={MediaType.IMAGE},
        )
    assert any(
        "cascade_fetch_media_failed" in r.message
        and "good_provider" in r.message
        for r in caplog.records
    ), f"expected warning, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_cascade_logs_no_results_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a provider returns [] from search, the cascade logs at DEBUG."""
    reg = ProviderRegistry()
    reg.register(_EmptyProvider())

    with caplog.at_level(logging.DEBUG, logger="multiscraper.providers.cascade"):
        await run_cascade(
            rom=_make_rom(),
            registry=reg,
            match_threshold=0.7,
            blocked_providers=set(),
            wanted_media={MediaType.IMAGE},
        )
    assert any(
        "cascade_provider_no_results" in r.message
        and "empty_provider" in r.message
        for r in caplog.records
    ), f"expected debug log, got: {[r.message for r in caplog.records]}"
