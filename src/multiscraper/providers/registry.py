"""ProviderRegistry: auto-discovery and lookup of providers by media type."""

from __future__ import annotations

from collections import defaultdict

from multiscraper.models import MediaType
from multiscraper.providers.base import Identifier, Provider


class ProviderRegistry:
    """Registry of all available providers, indexed by name and media type."""

    def __init__(self) -> None:
        self._by_name: dict[str, Provider] = {}
        self._by_media_type: dict[MediaType, list[Provider]] = defaultdict(list)
        self._identifiers: list[Identifier] = []

    def register(self, provider: Provider) -> None:
        """Register a provider. Must have a unique name."""
        self._by_name[provider.name] = provider
        for mt in provider.supported_media:
            self._by_media_type[mt].append(provider)
        identify = getattr(provider, "identify", None)
        if callable(identify):
            self._identifiers.append(provider)  # type: ignore[arg-type]

    def get(self, name: str) -> Provider | None:
        """Get a provider by name."""
        return self._by_name.get(name)

    def providers_for_media(self, mt: MediaType) -> list[Provider]:
        """Get all providers that offer this media type, sorted by priority."""
        return sorted(self._by_media_type.get(mt, []), key=lambda p: p.priority)

    @property
    def identifiers(self) -> list[Identifier]:
        """All registered identifier providers."""
        return self._identifiers

    @property
    def all_providers(self) -> list[Provider]:
        """All registered providers, sorted by priority."""
        return sorted(self._by_name.values(), key=lambda p: p.priority)
