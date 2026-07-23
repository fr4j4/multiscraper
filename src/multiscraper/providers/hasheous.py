"""Hasheous identifier provider for multiscraper.

Auth: none required.
Lookup: GET https://hasheous.org/api/v1/hasheous/lookup/<hash>
Returns: IdentifierResult (canonical name + platform) for cascade to use.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp

from multiscraper.models import Rom
from multiscraper.providers.base import Identifier, IdentifierResult

_BASE_URL = "https://hasheous.org/api/v1/hasheous/lookup"


class HasheousIdentifier:
    """Hasheous hash-based identifier.

    Implements the Identifier Protocol (not Provider).
    """

    name: ClassVar[str] = "hasheous"
    is_identifier_only: ClassVar[bool] = True
    health_url: ClassVar[str | None] = "https://hasheous.org/"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def identify(self, rom: Rom) -> IdentifierResult | None:
        if self._session is None:
            return None
        hash_to_try = rom.rom_id.sha1 or rom.rom_id.crc32
        if not hash_to_try:
            return None
        url = f"{_BASE_URL}/{hash_to_try}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        name = data.get("name")
        if not name:
            return None
        return IdentifierResult(
            canonical_name=name,
            platform=data.get("platform", rom.system),
            source_id=hash_to_try,
            provider=self.name,
            confidence=0.8,
        )


assert isinstance(HasheousIdentifier(), Identifier)
