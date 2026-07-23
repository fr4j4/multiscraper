"""OpenVGDB provider for multiscraper.

Auth: none required.
Search: GET https://vgdb.io/search?q=<name> and parse HTML with lxml.
Media: IMAGE populated with placeholder cover URL.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from lxml import etree
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_BASE_URL = "https://vgdb.io"


class OpenVGDBProvider:
    """OpenVGDB HTML-scraping provider."""

    name: ClassVar[str] = "openvgdb"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1.0
    priority: ClassVar[int] = 45
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE}
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False
    health_url: ClassVar[str | None] = "https://github.com/OpenVGDB/OpenVGDB"

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
        params: dict[str, str] = {"q": rom.normalized_name}
        url = f"{_BASE_URL}/search"
        async with self._session.get(url, params=params) as resp:
            body = await resp.read()
            if self.detect_blocked(resp, body):
                return []
            if resp.status != 200:
                return []
            html = body

        try:
            parser = etree.HTMLParser()
            root = etree.fromstring(html, parser=parser)
        except Exception:
            return []
        if root is None:
            return []

        candidates: list[Candidate] = []
        for link in root.iter("a"):
            cls = link.get("class")
            if cls is None or "game" not in cls.split():
                continue
            href = link.get("href")
            if not isinstance(href, str) or not href:
                continue
            parts = href.rstrip("/").split("/")
            gid = parts[-1] if parts else ""
            if not gid:
                continue
            raw_title = "".join(
                t for t in link.itertext() if isinstance(t, str)
            ).strip()
            title = raw_title.split(" (")[0].strip() or rom.normalized_name
            score = compute_match_score(rom.normalized_name, title)
            cover_url = f"{_BASE_URL}/game/{gid}/cover.png"
            media_refs: list[MediaRef] = [
                MediaRef(
                    type=MediaType.IMAGE,
                    url=HttpUrl(cover_url),
                    ext="png",
                    source=self.name,
                ),
            ]
            candidates.append(Candidate(
                provider=self.name,
                source_id=gid,
                name=title,
                match_score=score,
                media=media_refs,
            ))
        return candidates

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
        msg = str(exc).lower()
        return "api_key" in msg or "401" in msg or "403" in msg
