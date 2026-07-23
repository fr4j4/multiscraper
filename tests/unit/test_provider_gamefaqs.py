"""Tests for GameFAQs provider (mocked HTTP, HTML parse, block detection)."""

import re
from typing import ClassVar

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.gamefaqs import GameFAQsProvider

_SEARCH_URL = re.compile(r"https://gamefaqs\.gamespot\.com/search.*")
_GAME_URL = re.compile(r"https://gamefaqs\.gamespot\.com/.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


def _search_html() -> bytes:
    return (
        b'<html><body>'
        b'<a class="result" href="/snes/123-test-game">Test Game (1990)</a>'
        b'<a class="result" href="/snes/456-another-game">Another Game (1991)</a>'
        b'</body></html>'
    )


def _game_html() -> bytes:
    return (
        b'<html><body>'
        b'<div class="game_title">Test Game</div>'
        b'<p class="desc">A description of Test Game.</p>'
        b'</body></html>'
    )


@pytest.mark.asyncio
async def test_gamefaqs_search_returns_candidates():
    provider = GameFAQsProvider()
    await provider.setup({})

    with aioresponses() as m:
        m.get(_SEARCH_URL, status=200, body=_search_html())
        m.get(_GAME_URL, status=200, body=_game_html())
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) >= 1
    first = candidates[0]
    assert first.provider == "gamefaqs"
    assert first.match_score > 0.5
    assert first.description is not None
    assert any(ref.type == MediaType.IMAGE for ref in first.media)

    await provider.close()


@pytest.mark.asyncio
async def test_gamefaqs_search_returns_empty_when_blocked():
    provider = GameFAQsProvider()
    await provider.setup({})

    with aioresponses() as m:
        m.get(
            _SEARCH_URL, status=503,
            body=b"<html>cloudflare challenge: just a moment</html>",
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert candidates == []

    await provider.close()


@pytest.mark.asyncio
async def test_gamefaqs_detect_blocked():
    provider = GameFAQsProvider()
    await provider.setup({})

    class BlockedResp:
        status: ClassVar[int] = 403
        headers: ClassVar[dict[str, str]] = {}

    class OkResp:
        status: ClassVar[int] = 200
        headers: ClassVar[dict[str, str]] = {}

    assert provider.detect_blocked(
        BlockedResp(), b"<!doctype html>cloudflare</html>",
    ) is True
    assert provider.detect_blocked(OkResp(), b"<!doctype html>ok</html>") is False

    await provider.close()
