"""GameFAQs provider for multiscraper (last-resort HTML scraping).

Auth: none required.
Search: GET https://gamefaqs.gamespot.com/search?game=<name>; parse HTML
        and follow the first result link to fetch the game page for description.
Media: IMAGE declared (placeholder for v1).
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from lxml import etree
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_BASE_URL = "https://gamefaqs.gamespot.com"


class GameFAQsProvider:
    """GameFAQs HTML-scraping provider (last-resort)."""

    name: ClassVar[str] = "gamefaqs"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 0.5
    priority: ClassVar[int] = 50
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE}
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False
    health_url: ClassVar[str | None] = "https://gamefaqs.gamespot.com/"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None:
            return []
        params: dict[str, str] = {"game": rom.normalized_name}
        search_url = f"{_BASE_URL}/search"
        async with self._session.get(search_url, params=params) as resp:
            body = await resp.read()
            if self.detect_blocked(resp, body):
                return []
            if resp.status != 200:
                return []
            search_html = body

        result_links = self._extract_result_links(search_html)
        if not result_links:
            return []

        first_href, first_title = result_links[0]
        game_url = first_href if first_href.startswith("http") else f"{_BASE_URL}{first_href}"
        description = await self._fetch_description(game_url)

        score = compute_match_score(rom.normalized_name, first_title)
        cover_url = f"{_BASE_URL}/images/cover/{first_title.lower().replace(' ', '-')}.jpg"
        media_refs: list[MediaRef] = [
            MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl(cover_url),
                ext="jpg",
                source=self.name,
            ),
        ]
        return [Candidate(
            provider=self.name,
            source_id=first_href,
            name=first_title,
            match_score=score,
            description=description,
            media=media_refs,
        )]

    def _extract_result_links(self, html: bytes) -> list[tuple[str, str]]:
        try:
            parser = etree.HTMLParser()
            root = etree.fromstring(html, parser=parser)
        except Exception:
            return []
        if root is None:
            return []
        results: list[tuple[str, str]] = []
        for link in root.iter("a"):
            cls = link.get("class")
            if cls is None or "result" not in cls.split():
                continue
            href = link.get("href")
            if not isinstance(href, str) or not href:
                continue
            text = "".join(t for t in link.itertext() if isinstance(t, str)).strip()
            if not text:
                continue
            results.append((href, text))
        return results

    async def _fetch_description(self, game_url: str) -> str | None:
        if self._session is None:
            return None
        async with self._session.get(game_url) as resp:
            body = await resp.read()
            if self.detect_blocked(resp, body):
                return None
            if resp.status != 200:
                return None
        try:
            parser = etree.HTMLParser()
            root = etree.fromstring(body, parser=parser)
        except Exception:
            return None
        if root is None:
            return None
        for elem in root.iter("p"):
            cls = elem.get("class")
            if cls is not None and "desc" in cls.split():
                text = "".join(t for t in elem.itertext() if isinstance(t, str)).strip()
                if text:
                    return text
        return None

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        result: dict[MediaType, MediaRef] = {}
        for mt in wanted:
            for ref in candidate.media:
                if ref.type == mt and mt not in result:
                    result[mt] = ref
                    break
        return result

    def detect_blocked(self, response: object, body: bytes) -> bool:
        status = getattr(response, "status", 200)
        headers_obj = getattr(response, "headers", {})
        headers: dict[str, str] = {str(k): str(v) for k, v in dict(headers_obj).items()}
        return detect_blocked(status, body, headers)

    def is_auth_missing(self, exc: Exception) -> bool:
        return False
