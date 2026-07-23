"""Tests for GiantBomb provider (mocked HTTP)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.giantbomb import GiantBombProvider

_GB_URL = re.compile(r"https://www\.giantbomb\.com/api/games/.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_giantbomb_search_returns_candidates():
    provider = GiantBombProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"status_code":1,"results":[{'
        b'"id":"3030-1234","name":"Test Game",'
        b'"deck":"A retro game","description":"Long description",'
        b'"image":{"screen_url":"https://example.com/screen.jpg",'
        b'"thumb_url":"https://example.com/thumb.jpg"},'
        b'"platforms":[{"name":"SNES","abbreviation":"snes"}]}]}'
    )

    with aioresponses() as m:
        m.get(_GB_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "3030-1234"
    assert candidates[0].match_score > 0.5
    assert candidates[0].description is not None
    assert "Long description" in candidates[0].description

    await provider.close()


@pytest.mark.asyncio
async def test_giantbomb_fetch_media_from_candidate():
    provider = GiantBombProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"status_code":1,"results":[{'
        b'"id":"3030-1234","name":"Test",'
        b'"image":{"screen_url":"https://example.com/screen.jpg",'
        b'"thumb_url":"https://example.com/thumb.jpg"},'
        b'"video":{"site_detail_url":"https://example.com/video.mp4"}}]}'
    )

    with aioresponses() as m:
        m.get(_GB_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(
        candidates[0], {MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO},
    )

    assert MediaType.IMAGE in media
    assert MediaType.THUMBNAIL in media
    assert MediaType.VIDEO in media
    assert "screen.jpg" in str(media[MediaType.IMAGE].url)
    assert "thumb.jpg" in str(media[MediaType.THUMBNAIL].url)
    assert "video.mp4" in str(media[MediaType.VIDEO].url)

    await provider.close()


@pytest.mark.asyncio
async def test_giantbomb_detect_blocked():
    provider = GiantBombProvider()
    await provider.setup({"api_key": "key123"})

    class FakeResp:
        status: int = 403

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    assert provider.detect_blocked(FakeResp(), b"<html>cloudflare</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>ok</html>") is False

    await provider.close()
