"""ProviderRegistry: auto-discovery and lookup of providers by media type."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from multiscraper.models import MediaType
from multiscraper.providers.base import Identifier, Provider


class ProviderRegistry:
    """Registry of all available providers, indexed by name and media type."""

    def __init__(self) -> None:
        self._by_name: dict[str, Provider] = {}
        self._by_media_type: dict[MediaType, list[Provider]] = defaultdict(list)
        self._identifiers: list[Identifier] = []
        self._classes_by_name: dict[str, type[Any]] = {}

    def register(self, provider: Provider) -> None:
        """Register a provider. Must have a unique name."""
        self._by_name[provider.name] = provider
        for mt in provider.supported_media:
            self._by_media_type[mt].append(provider)
        identify = getattr(provider, "identify", None)
        if callable(identify):
            self._identifiers.append(provider)  # type: ignore[arg-type]

    def register_class(self, cls: type[Any]) -> None:
        """Register a provider class for later instantiation by name."""
        name = getattr(cls, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{cls!r} has no usable name classvar")
        self._classes_by_name[name] = cls

    def get_class(self, name: str) -> type[Any] | None:
        """Look up a registered provider class by its name attribute."""
        return self._classes_by_name.get(name)

    def instantiate(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Instantiate a provider class previously registered with register_class."""
        cls = self._classes_by_name.get(name)
        if cls is None:
            raise LookupError(f"provider class not registered: {name!r}")
        return cls(*args, **kwargs)

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
