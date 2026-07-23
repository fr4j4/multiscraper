"""Tests for TheGamesDB provider (mocked HTTP)."""

import re
from typing import ClassVar

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.thegamesdb import TheGamesDBProvider

_TGDB_URL = re.compile(r"https://api\.thegamesdb\.net/v2/Games/ByGameName.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_thegamesdb_search_returns_candidates():
    provider = TheGamesDBProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"code":200,"status":"Success","data":{"games":[{'
        b'"id":456,"name":"Test Game",'
        b'"release_date":"1990-01-01",'
        b'"platform":6}]}}'
    )

    with aioresponses() as m:
        m.get(_TGDB_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id == "456"
    assert candidates[0].match_score > 0.5

    await provider.close()


@pytest.mark.asyncio
async def test_thegamesdb_fetch_media_from_candidate():
    provider = TheGamesDBProvider()
    await provider.setup({"api_key": "key123"})

    body = (
        b'{"code":200,"status":"Success","data":{"games":[{'
        b'"id":456,"name":"Test Game",'
        b'"platform":6}]}}'
    )

    with aioresponses() as m:
        m.get(_TGDB_URL, status=200, body=body)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(
        candidates[0], {MediaType.IMAGE, MediaType.THUMBNAIL},
    )

    assert media == {}

    await provider.close()


@pytest.mark.asyncio
async def test_thegamesdb_detect_blocked():
    provider = TheGamesDBProvider()
    await provider.setup({"api_key": "key123"})

    class BlockedResp:
        status: ClassVar[int] = 403
        headers: ClassVar[dict[str, str]] = {"cf-ray": "abc"}

    class OkResp:
        status: ClassVar[int] = 200
        headers: ClassVar[dict[str, str]] = {}

    assert provider.detect_blocked(BlockedResp(), b"ok") is True
    assert provider.detect_blocked(OkResp(), b"ok") is False

    await provider.close()
