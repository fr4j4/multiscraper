"""Tests for MobyGames provider (mocked HTTP)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.mobygames import MobyGamesProvider

_GAMES_URL = re.compile(r"https://api\.mobygames\.com/v1/games(?:\?.*)?$")
_COVERS_URL = re.compile(r"https://api\.mobygames\.com/v1/games/\d+/covers(?:\?.*)?$")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_mobygames_search_returns_candidates():
    provider = MobyGamesProvider()
    await provider.setup({"api_key": "key123"})

    games_body = (
        b'{"games":[{"game_id":1234,"title":"Test Game",'
        b'"description":"A retro game","platforms":[15],'
        b'"genres":[{"genre_name":"Action"}],'
        b'"release_date":"1990"}]}'
    )
    covers_body = (
        b'{"covers":[{"image":"https://example.com/cover.jpg"}]}'
    )

    with aioresponses() as m:
        m.get(_GAMES_URL, status=200, body=games_body)
        m.get(_COVERS_URL, status=200, body=covers_body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "1234"
    assert candidates[0].match_score > 0.5
    assert candidates[0].description == "A retro game"
    assert candidates[0].genre == "Action"

    await provider.close()


@pytest.mark.asyncio
async def test_mobygames_fetch_media_from_candidate():
    provider = MobyGamesProvider()
    await provider.setup({"api_key": "key123"})

    games_body = (
        b'{"games":[{"game_id":1234,"title":"Test","platforms":[15]}]}'
    )
    covers_body = (
        b'{"covers":[{"image":"https://example.com/cover.jpg"}]}'
    )

    with aioresponses() as m:
        m.get(_GAMES_URL, status=200, body=games_body)
        m.get(_COVERS_URL, status=200, body=covers_body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(candidates[0], {MediaType.IMAGE, MediaType.THUMBNAIL})

    assert MediaType.IMAGE in media
    assert "example.com/cover.jpg" in str(media[MediaType.IMAGE].url)

    await provider.close()


@pytest.mark.asyncio
async def test_mobygames_detect_blocked():
    provider = MobyGamesProvider()
    await provider.setup({"api_key": "key123"})

    class FakeResp:
        status: int = 403

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    assert provider.detect_blocked(FakeResp(), b"<html>cloudflare</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>ok</html>") is False

    await provider.close()
