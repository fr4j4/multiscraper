"""Tests for RetroAchievements provider (mocked HTTP)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.retroachievements import RetroAchievementsProvider

_RA_URL = re.compile(r"https://retroachievements\.org/API/.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_retroachievements_search_returns_candidates():
    provider = RetroAchievementsProvider()
    await provider.setup({"username": "user", "api_key": "key123"})

    body = (
        b'{"Response":[{'
        b'"Title":"Test Game","ID":123,'
        b'"ImageIcon":"/Images/000001.png",'
        b'"ImageTitle":"/Images/000001_title.png",'
        b'"ConsoleID":3}]}'
    )

    with aioresponses() as m:
        m.get(_RA_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "123"
    assert candidates[0].match_score > 0.5
    assert len(candidates[0].media) >= 1

    await provider.close()


@pytest.mark.asyncio
async def test_retroachievements_fetch_media_from_candidate():
    provider = RetroAchievementsProvider()
    await provider.setup({"username": "user", "api_key": "key123"})

    body = (
        b'{"Response":[{'
        b'"Title":"Test Game","ID":123,'
        b'"ImageIcon":"/Images/000001.png",'
        b'"ImageTitle":"/Images/000001_title.png",'
        b'"ConsoleID":3}]}'
    )

    with aioresponses() as m:
        m.get(_RA_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(
        candidates[0], {MediaType.IMAGE, MediaType.LOGO},
    )

    assert MediaType.IMAGE in media
    assert MediaType.LOGO in media
    assert "000001.png" in str(media[MediaType.IMAGE].url)
    assert "000001_title.png" in str(media[MediaType.LOGO].url)

    await provider.close()


@pytest.mark.asyncio
async def test_retroachievements_detect_blocked():
    provider = RetroAchievementsProvider()
    await provider.setup({"username": "user", "api_key": "key123"})

    class BlockedResp:
        status: int = 429

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    class OkResp:
        status: int = 200

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    assert provider.detect_blocked(BlockedResp(), b"rate limit exceeded") is True
    assert provider.detect_blocked(OkResp(), b"ok") is False

    await provider.close()
