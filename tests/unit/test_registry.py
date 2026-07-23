"""Tests for ProviderRegistry."""

from typing import ClassVar

from multiscraper.models import MediaType, Rom
from multiscraper.providers.base import IdentifierResult
from multiscraper.providers.registry import ProviderRegistry


class FakeProvider:
    name = "fake"
    requires_auth = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec = 2.0
    priority = 5
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE, MediaType.VIDEO}
    platform_map: ClassVar[dict[str, str | int]] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None: pass
    async def close(self) -> None: pass
    async def search(self, rom: Rom) -> list[object]: return []
    async def fetch_media(
        self, candidate: object, wanted: object
    ) -> dict[object, object]: return {}
    def detect_blocked(self, response: object, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


class FakeIdentifier:
    name = "fake_ident"

    async def identify(self, rom: Rom) -> IdentifierResult | None:
        return None


def test_registry_register_provider() -> None:
    reg = ProviderRegistry()
    p = FakeProvider()
    reg.register(p)
    assert reg.get("fake") is p


def test_registry_providers_for_media() -> None:
    reg = ProviderRegistry()
    reg.register(FakeProvider())
    providers = reg.providers_for_media(MediaType.IMAGE)
    assert len(providers) == 1
    assert providers[0].name == "fake"


def test_registry_providers_for_media_empty() -> None:
    reg = ProviderRegistry()
    providers = reg.providers_for_media(MediaType.MARQUEE)
    assert len(providers) == 0


def test_registry_sorted_by_priority() -> None:
    class HighPriority(FakeProvider):
        name = "high"
        priority = 1
    class LowPriority(FakeProvider):
        name = "low"
        priority = 100

    reg = ProviderRegistry()
    reg.register(LowPriority())
    reg.register(HighPriority())
    providers = reg.providers_for_media(MediaType.IMAGE)
    assert providers[0].name == "high"
    assert providers[1].name == "low"
