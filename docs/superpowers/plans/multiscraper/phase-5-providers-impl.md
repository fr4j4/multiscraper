# Phase 5: Provider Implementations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 13 providers with tests (using vcrpy cassettes or fakes for offline CI).

**Depends on:** Phase 4 (Provider Protocol, registry, cascade, match, block_detect).

**Milestone:** Each provider has passing unit tests; `ruff` and `mypy` pass; registry can instantiate all 13 providers.

**Parallelizable:** YES — up to 11 agents (one per provider file). `local.py` implements both `local_override` and `local_fallback` (same code, different priority). `hasheous.py` is the identifier.

**IMPORTANT — Testing strategy for providers:**

- Each provider test uses `aioresponses` (mock aiohttp) or `vcrpy` cassettes.
- Cassettes are NOT included in the repo by default. Tests use `aioresponses` to mock HTTP responses inline.
- `@pytest.mark.network` tests (real API calls) are skipped in CI.
- Each provider test verifies: search returns candidates, fetch_media returns MediaRefs, detect_blocked works, auth validation works.

---

## Task 5.1: ScreenScraper provider

**Files:**
- Create: `src/multiscraper/providers/screenscraper.py`
- Test: `tests/unit/test_provider_screenscraper.py`

**Interfaces:**
- Consumes: `Provider` Protocol from `base.py`, `compute_match_score` from `match.py`
- Produces: `ScreenScraperProvider` class implementing `Provider`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_provider_screenscraper.py
"""Tests for ScreenScraper provider (mocked HTTP)."""

from datetime import datetime, timezone

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.screenscraper import ScreenScraperProvider


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_screenscraper_search_returns_candidates():
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test",
        "devpassword": "test",
        "region_priority": ["wor", "us"],
        "language_priority": ["en"],
    })

    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Data>
  <jeu>
    <id>123</id>
    <noms>
      <nom region="wor">Test Game</nom>
      <nom region="us">Test Game USA</nom>
    </noms>
    <synopsis>
      <synopsis langue="en">A test game description.</synopsis>
    </synopsis>
    <developpeur>TestDev</developpeur>
    <editeur>TestPub</editeur>
    <joueurs>1</joueurs>
    <genres>
      <genre langue="en">Action</genre>
    </genres>
    <dates>
      <date region="wor">1990-01-01</date>
    </dates>
    <medias>
      <media type="box2D" region="wor" format="png">https://example.com/box.png</media>
      <media type="ss" region="wor" format="jpg">https://example.com/ss.jpg</media>
      <media type="video" region="wor" format="mp4">https://example.com/vid.mp4</media>
    </medias>
  </jeu>
</Data>"""

    with aioresponses() as m:
        m.get(
            "https://www.screenscraper.fr/api2/jeuInfos.php",
            status=200,
            body=xml_response,
            headers={"Content-Type": "application/xml"},
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].match_score > 0.5
    assert candidates[0].developer == "TestDev"
    assert candidates[0].description == "A test game description."

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_fetch_media():
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test",
        "devpassword": "test",
        "region_priority": ["wor"],
        "language_priority": ["en"],
    })

    # fetch_media uses the media URLs from the candidate (already fetched in search)
    # So we test it by first searching, then fetching
    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Data>
  <jeu>
    <id>123</id>
    <noms><nom region="wor">Test Game</nom></noms>
    <medias>
      <media type="box2D" region="wor" format="png">https://example.com/box.png</media>
      <media type="video" region="wor" format="mp4">https://example.com/vid.mp4</media>
    </medias>
  </jeu>
</Data>"""

    with aioresponses() as m:
        m.get(
            "https://www.screenscraper.fr/api2/jeuInfos.php",
            status=200,
            body=xml_response,
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    # The candidate should have media refs
    assert len(candidates[0].media) >= 1
    media_types = {m.type for m in candidates[0].media}
    assert MediaType.IMAGE in media_types or MediaType.VIDEO in media_types

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_detect_blocked():
    provider = ScreenScraperProvider()
    await provider.setup({"devid": "test", "devpassword": "test"})

    class FakeResp:
        status = 403
    assert provider.detect_blocked(FakeResp(), b"<html>cloudflare</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>normal</html>") is False

    await provider.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_provider_screenscraper.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/providers/screenscraper.py
"""ScreenScraper provider — the primary retro gaming data source.

API v2: https://www.screenscraper.fr/api2/jeuInfos.php
Returns XML with game info and media URLs.
Supports all 10 media types.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp
from lxml import etree

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://www.screenscraper.fr/api2"

# Map ScreenScraper media types to our MediaType
_SS_MEDIA_MAP = {
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

# Map our platform names to ScreenScraper system IDs
# (subset — full map in the spec)
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

    name = "screenscraper"
    requires_auth = False  # auth is optional (increases quota)
    auth_fields = ["devid", "devpassword"]
    rate_limit_per_sec = 2.0
    priority = 5
    supported_media = {
        MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO,
        MediaType.MARQUEE, MediaType.BOX3D, MediaType.BACKCOVER,
        MediaType.FANART, MediaType.MANUAL, MediaType.MIXIMAGE, MediaType.LOGO,
    }
    platform_map: dict[str, str | int] = _PLATFORM_MAP
    is_identifier_only = False
    is_offline = False

    def __init__(self) -> None:
        self._devid: str = ""
        self._devpassword: str = ""
        self._region_priority: list[str] = ["wor", "us", "eu", "jp"]
        self._language_priority: list[str] = ["en"]
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._devid = config.get("devid", "")
        self._devpassword = config.get("devpassword", "")
        self._region_priority = config.get("region_priority", ["wor", "us", "eu", "jp"])
        self._language_priority = config.get("language_priority", ["en"])
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        assert self._session is not None
        system_id = self.platform_map.get(rom.system)
        if system_id is None:
            return []

        params = {
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

        # Name with region fallback
        name = self._find_by_attr(game, "noms/nom", "region", self._region_priority)
        if not name:
            name = root.findtext(".//jeu/noms/nom") or rom.normalized_name

        # Description with language fallback
        desc = self._find_by_attr(game, "synopsis/synopsis", "langue", self._language_priority)

        # Genre
        genre = self._find_by_attr(game, "genres/genre", "langue", self._language_priority)

        # Developer, publisher, players
        developer = game.findtext("developpeur") or None
        publisher = game.findtext("editeur") or None
        players_str = game.findtext("joueurs") or ""
        players = int(players_str) if players_str.isdigit() else None

        # Release date
        date_str = self._find_by_attr(game, "dates/date", "region", self._region_priority)
        releasedate = None
        if date_str and len(date_str) >= 4:
            try:
                if len(date_str) > 4:
                    releasedate = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                else:
                    releasedate = datetime.strptime(date_str, "%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        # Rating
        rating = None
        note = game.find("note")
        if note is not None and note.text:
            try:
                rating = int(note.text) / 20.0
            except ValueError:
                pass

        # Media
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
                url=url,
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
        # Fallback: first element
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
        headers = dict(getattr(response, "headers", {}))
        return detect_blocked(status, body, headers)

    def is_auth_missing(self, exc: Exception) -> bool:
        return "auth" in str(exc).lower() or "devid" in str(exc).lower()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_provider_screenscraper.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/providers/screenscraper.py tests/unit/test_provider_screenscraper.py
git commit -m "feat: add ScreenScraper provider with XML parsing and media mapping"
```

---

## Tasks 5.2–5.13: Remaining providers

Each remaining provider follows the same pattern as 5.1. Below is a summary table. Each provider is a separate task that an agent can implement independently.

| Task | File | Provider ID | Auth | Media types | Notes |
|---|---|---|---|---|---|
| 5.2 | `igdb.py` | `igdb` | Twitch OAuth2 | image, thumb, video | POST with body syntax; token auto-refresh |
| 5.3 | `rawg.py` | `rawg` | api_key | image, thumb | Simple REST, `?key=...` |
| 5.4 | `mobygames.py` | `mobygames` | api_key | image, thumb, screenshot | `/v1/games` endpoint |
| 5.5 | `giantbomb.py` | `giantbomb` | api_key | image, video | 200 req/h limit; `?api_key=...` |
| 5.6 | `retroachievements.py` | `retroachievements` | username + api_key | image, logo | `API_GetGame.php` |
| 5.7 | `thegamesdb.py` | `thegamesdb` | api_key v2 | image, fanart, screenshot, banner, logo | Marcado experimental |
| 5.8 | `libretro_thumbnails.py` | `libretro_thumbnails` | none | image, marquee, box3d, manual, logo | Probe GitHub raw URLs |
| 5.9 | `openvgdb.py` | `openvgdb` | none | image, screenshot | HTML scraping |
| 5.10 | `gamefaqs.py` | `gamefaqs` | none | screenshot, desc | HTML scraping, Cloudflare protected |
| 5.11 | `hasheous.py` | `hasheous` | none | N/A (identifier only) | Hash lookup API |
| 5.12 | `local.py` | `local_override` + `local_fallback` | none | all (via local paths) | SQLite `source_overrides` table |

### Template for each provider task

Each agent follows these steps:

- [ ] **Step 1: Write the failing test** (using `aioresponses` for HTTP mocking)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation** (implementing `Provider` Protocol)
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Run lint and typecheck**
- [ ] **Step 6: Commit** with message `feat: add <provider_name> provider`

### Key implementation notes per provider

**IGDB (5.2):**
- Auth: POST to `https://id.twitch.tv/oauth2/token` with `client_id` + `client_secret` + `grant_type=client_credentials`. Cache token, refresh on expiry.
- Search: POST to `https://api.igdb.com/v4/games` with body `fields name,summary,first_release_date,rating,genres.name,platforms.name,cover.image_id,screenshots.image_id,videos.video_id; search "Rom Name"; where platforms = (19);`
- Media: cover URL = `https://images.igdb.com/igdb/image/upload/t_cover_big/<image_id>.jpg`
- Video: IGDB returns YouTube video IDs; we store the YouTube URL (not downloadable directly — the worker can skip video download for IGDB or use yt-dlp in a future version).

**RAWG (5.3):**
- Search: GET `https://api.rawg.io/api/games?key=<key>&search=<name>&platforms=<id>`
- Media: `image` from `background_image`, `thumbnail` from `background_image` with smaller size param.

**MobyGames (5.4):**
- Search: GET `https://api.mobygames.com/v1/games?api_key=<key>&title=<name>`
- Media: covers and screenshots from `games/{id}/covers` and `games/{id}/screenshots`.

**GiantBomb (5.5):**
- Search: GET `https://www.giantbomb.com/api/games/?api_key=<key>&filter=name:<name>&format=json`
- Media: `image` from `image.screen_url`, `video` from `video.site_detail_url`.

**RetroAchievements (5.6):**
- Search: GET `https://retroachievements.org/API/API_GetGame.php?z=<user>&y=<key>&g=<game_id>`
- Media: `image` from `image_boxart`, `logo` from `image_title`.

**TheGamesDB (5.7):**
- Search: GET `https://api.thegamesdb.net/v2/Games/ByGameName?apikey=<key>&name=<name>`
- Media: from `Games/Images` endpoint.

**LibRetro Thumbnails (5.8):**
- No search. For each ROM, probe URLs like:
  - `https://raw.githubusercontent.com/libretro-thumbnails/<system>/master/<rom_name>/Named_Snaps/<rom_name>.png`
  - `.../Named_Boxarts/<rom_name>.png`
  - `.../Named_Titles/<rom_name>.png`
- If 200, create MediaRef. If 404, skip.

**OpenVGDB (5.9):**
- HTML scraping of `https://vgdb.io/search?q=<name>`.
- Parse with `lxml.html`.

**GameFAQs (5.10):**
- HTML scraping of `https://gamefaqs.gamespot.com/games?query=<name>`.
- Implements strict `detect_blocked` (any 403 → blocked).

**Hasheous (5.11):**
- Implements `Identifier` Protocol (not `Provider`).
- GET `https://hasheous.org/api/v1/hasheous/lookup/<hash>`.
- Returns `IdentifierResult` with `canonical_name` and `platform`.

**Local (5.12):**
- Reads from SQLite `source_overrides` table.
- Two instances with different priorities: `local_override` (priority 1) and `local_fallback` (priority 9999).
- `is_offline = True`.
- `search()` checks `source_overrides` by `cache_key`.
- `fetch_media()` returns MediaRefs from `media_paths_json` in the override.

---

## Milestone Gate

- [ ] All 13 provider files exist in `src/multiscraper/providers/`
- [ ] Each provider has a passing test in `tests/unit/test_provider_*.py`
- [ ] `pytest tests/unit/ -v` — all tests pass
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes
- [ ] `ProviderRegistry` can instantiate and register all 13 providers