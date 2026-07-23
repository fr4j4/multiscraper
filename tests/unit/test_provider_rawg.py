"""Tests for RAWG provider (mocked HTTP)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.rawg import RAWGProvider

_RAWG_URL = re.compile(r"https://api\.rawg\.io/api/games.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_rawg_search_returns_candidates():
    provider = RAWGProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"count":1,"results":[{"id":1,"name":"Test Game",'
        b'"released":"1990-01-01","rating":4.5,'
        b'"background_image":"https://example.com/bg.jpg",'
        b'"genres":[{"name":"Action"}],'
        b'"platforms":[{"platform":{"slug":"snes","name":"SNES"}}]}]}'
    )

    with aioresponses() as m:
        m.get(_RAWG_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "1"
    assert candidates[0].match_score > 0.5
    assert candidates[0].rating == 4.5
    assert candidates[0].genre == "Action"

    await provider.close()


@pytest.mark.asyncio
async def test_rawg_fetch_media_from_candidate():
    provider = RAWGProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"count":1,"results":[{"id":1,"name":"Test",'
        b'"background_image":"https://example.com/bg.jpg"}]}'
    )

    with aioresponses() as m:
        m.get(_RAWG_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(candidates[0], {MediaType.IMAGE, MediaType.THUMBNAIL})

    assert MediaType.IMAGE in media
    assert MediaType.THUMBNAIL in media
    assert "example.com/bg.jpg" in str(media[MediaType.IMAGE].url)

    await provider.close()


@pytest.mark.asyncio
async def test_rawg_detect_blocked():
    provider = RAWGProvider()
    await provider.setup({"api_key": "key123"})

    class FakeResp:
        status: int = 403

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    assert provider.detect_blocked(FakeResp(), b"<html>captcha</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>ok</html>") is False

    await provider.close()
