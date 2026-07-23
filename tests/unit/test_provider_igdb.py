"""Tests for IGDB provider (mocked HTTP)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.igdb import IGDBProvider

_TOKEN_URL = re.compile(r"https://id\.twitch\.tv/oauth2/token.*")
_GAMES_URL = re.compile(r"https://api\.igdb\.com/v4/games.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_igdb_search_returns_candidates():
    provider = IGDBProvider()
    await provider.setup({"client_id": "cid", "client_secret": "csec"})

    token_body = b'{"access_token":"abc123","expires_in":3600,"token_type":"bearer"}'
    games_body = (
        b'[{"id":1234,"name":"Test Game","summary":"A retro game",'
        b'"rating":85.0,"cover":{"image_id":"co1234"},'
        b'"screenshots":[{"image_id":"sc1234"}]}]'
    )

    with aioresponses() as m:
        m.post(_TOKEN_URL, status=200, body=token_body)
        m.post(_GAMES_URL, status=200, body=games_body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "1234"
    assert candidates[0].match_score > 0.5
    assert candidates[0].description == "A retro game"
    assert candidates[0].rating is not None
    assert abs(candidates[0].rating - 8.5) < 0.01

    await provider.close()


@pytest.mark.asyncio
async def test_igdb_fetch_media_from_candidate():
    provider = IGDBProvider()
    await provider.setup({"client_id": "cid", "client_secret": "csec"})

    token_body = b'{"access_token":"abc123","expires_in":3600,"token_type":"bearer"}'
    games_body = (
        b'[{"id":1234,"name":"Test","cover":{"image_id":"co1234"},'
        b'"screenshots":[{"image_id":"sc1234"}]}]'
    )

    with aioresponses() as m:
        m.post(_TOKEN_URL, status=200, body=token_body)
        m.post(_GAMES_URL, status=200, body=games_body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(candidates[0], {MediaType.IMAGE, MediaType.THUMBNAIL})

    assert MediaType.IMAGE in media
    assert MediaType.THUMBNAIL in media
    assert "co1234" in str(media[MediaType.IMAGE].url)
    assert "co1234" in str(media[MediaType.THUMBNAIL].url)

    await provider.close()


@pytest.mark.asyncio
async def test_igdb_detect_blocked():
    provider = IGDBProvider()
    await provider.setup({"client_id": "cid", "client_secret": "csec"})

    class FakeResp:
        status: int = 403

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    assert provider.detect_blocked(FakeResp(), b"<html>cloudflare</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>normal</html>") is False

    await provider.close()
