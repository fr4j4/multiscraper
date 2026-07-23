"""Tests for cascade logic with FakeProvider."""

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
from multiscraper.providers.base import IdentifierResult  # noqa: F401
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
async def test_cascade_all_blocked() -> None:
    reg = ProviderRegistry()
    reg.register(FakeGoodProvider())

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers={"good_provider"},
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.BLOCKED
