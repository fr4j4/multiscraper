"""ScreenScraper provider — the primary retro gaming data source.

API v2: https://www.screenscraper.fr/api2/jeuInfos.php
Returns XML with game info and media URLs.
Supports all 10 media types.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, ClassVar

import aiohttp
from lxml import etree
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://www.screenscraper.fr/api2"

_SS_MEDIA_MAP: dict[str, MediaType] = {
    "box2D": MediaType.IMAGE,
    "box2D-side": MediaType.IMAGE,
    "ss": MediaType.THUMBNAIL,
    "video": MediaType.VIDEO,
    "screenmarquee": MediaType.MARQUEE,
    "wheel": MediaType.MARQUEE,
    "box-3D": MediaType.BOX3D,
    "box2D-back": MediaType.BACKCOVER,
    "fanart": MediaType.FANART,
    "manuel": MediaType.MANUAL,
    "mixrbv1": MediaType.MIXIMAGE,
    "logo": MediaType.LOGO,
}

_PLATFORM_MAP: dict[str, int] = {
    "snes": 4, "nes": 3, "n64": 14, "gb": 9, "gba": 12, "gbc": 10,
    "nds": 15, "psx": 57, "ps2": 58, "ps3": 59, "psp": 61,
    "megadrive": 1, "snes-msu1": 210, "saturn": 22, "dreamcast": 23,
    "arcade": 75, "mame": 75, "atari2600": 26, "atari7800": 41,
    "gamegear": 21, "mastersystem": 2, "segacd": 20, "segaclassics": 147,
    "3do": 29, "neogeo": 142, "ngp": 25, "ngc": 82,
    "wonderswan": 45, "wonderswancolor": 46,
    "pcengine": 31, "pcenginecd": 114, "pcfx": 72,
    "amiga": 64, "c64": 66, "cpc": 65, "zx": 76,
    "msx": 113, "scummvm": 123, "switch": 225,
    "gc": 13, "wii": 16, "wiiu": 18,
    "xbox": 32, "xbox360": 33,
    "lynx": 28, "jaguar": 27, "virtualboy": 11,
    "coleco": 48, "intellivision": 115, "vectrex": 102,
}


class ScreenScraperProvider:
    """ScreenScraper API v2 provider."""

    name: ClassVar[str] = "screenscraper"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = ["devid", "devpassword"]
    rate_limit_per_sec: ClassVar[float] = 2.0
    priority: ClassVar[int] = 5
    supported_media: ClassVar[set[MediaType]] = {
        MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO,
        MediaType.MARQUEE, MediaType.BOX3D, MediaType.BACKCOVER,
        MediaType.FANART, MediaType.MANUAL, MediaType.MIXIMAGE, MediaType.LOGO,
    }
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._devid: str = ""
        self._devpassword: str = ""
        self._region_priority: list[str] = ["wor", "us", "eu", "jp"]
        self._language_priority: list[str] = ["en"]
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._devid = str(config.get("devid", ""))
        self._devpassword = str(config.get("devpassword", ""))
        self._region_priority = list(config.get("region_priority", ["wor", "us", "eu", "jp"]))
        self._language_priority = list(config.get("language_priority", ["en"]))
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None:
            return []
        system_id = self.platform_map.get(rom.system)
        if system_id is None:
            return []

        params: dict[str, str] = {
            "devid": self._devid,
            "devpassword": self._devpassword,
            "softname": "multiscraper",
            "output": "xml",
            "romnom": rom.raw_name,
            "systemeid": str(system_id),
        }
        if rom.rom_id.crc32:
            params["crc"] = rom.rom_id.crc32

        url = f"{_API_BASE}/jeuInfos.php"
        async with self._session.get(url, params=params) as resp:
            body = await resp.read()
            if self.detect_blocked(resp, body):
                return []
            if resp.status != 200:
                return []

        return self._parse_xml(body, rom)

    def _parse_xml(self, body: bytes, rom: Rom) -> list[Candidate]:
        """Parse ScreenScraper XML response into Candidates."""
        try:
            root = etree.fromstring(body)
        except etree.XMLSyntaxError:
            return []

        game = root.find(".//jeu")
        if game is None:
            return []

        name = self._find_by_attr(game, "noms/nom", "region", self._region_priority)
        if not name:
            name = root.findtext(".//jeu/noms/nom") or rom.normalized_name

        desc = self._find_by_attr(game, "synopsis/synopsis", "langue", self._language_priority)
        genre = self._find_by_attr(game, "genres/genre", "langue", self._language_priority)

        developer = game.findtext("developpeur") or None
        publisher = game.findtext("editeur") or None
        players_str = game.findtext("joueurs") or ""
        players: int | None = int(players_str) if players_str.isdigit() else None

        date_str = self._find_by_attr(game, "dates/date", "region", self._region_priority)
        releasedate: datetime | None = None
        if date_str and len(date_str) >= 4:
            try:
                if len(date_str) > 4:
                    releasedate = datetime.strptime(
                        date_str, "%Y-%m-%d",
                    ).replace(tzinfo=UTC)
                else:
                    releasedate = datetime.strptime(
                        date_str, "%Y",
                    ).replace(tzinfo=UTC)
            except ValueError:
                pass

        rating: float | None = None
        note = game.find("note")
        if note is not None and note.text:
            with contextlib.suppress(ValueError):
                rating = int(note.text) / 20.0

        media_refs: list[MediaRef] = []
        for media_elem in game.findall(".//medias/media"):
            ss_type = media_elem.get("type", "")
            region = media_elem.get("region", "")
            fmt = media_elem.get("format", "")
            url = media_elem.text or ""
            if not url:
                continue
            our_type = _SS_MEDIA_MAP.get(ss_type)
            if our_type is None:
                continue
            media_refs.append(MediaRef(
                type=our_type,
                url=HttpUrl(url),
                ext=fmt or "png",
                region=region,
                source=self.name,
            ))

        score = compute_match_score(rom.normalized_name, name)

        return [Candidate(
            provider=self.name,
            source_id=game.findtext("id") or "",
            name=name,
            match_score=score,
            releasedate=releasedate,
            developer=developer,
            publisher=publisher,
            genre=genre,
            players=players,
            rating=rating,
            description=desc,
            media=media_refs,
        )]

    def _find_by_attr(
        self, parent: etree._Element, xpath: str, attr: str, priorities: list[str],
    ) -> str | None:
        """Find a child element by attribute priority list."""
        for prio in priorities:
            elem = parent.find(f"{xpath}[@{attr}='{prio}']")
            if elem is not None and elem.text:
                return elem.text
        elem = parent.find(xpath)
        return elem.text if elem is not None and elem.text else None

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        """Return media refs from the candidate (already parsed in search)."""
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
        return "auth" in str(exc).lower() or "devid" in str(exc).lower()
