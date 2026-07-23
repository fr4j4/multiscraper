"""Tests for Hasheous identifier provider (mocked HTTP, JSON)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import Rom, RomIdentifier
from multiscraper.providers.base import Identifier
from multiscraper.providers.hasheous import HasheousIdentifier

_HASH_URL = re.compile(r"https://hasheous\.org/api/v1/hasheous/lookup/.*")


def _make_rom(crc32: str | None = None, sha1: str | None = None) -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32=crc32, sha1=sha1, cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_hasheous_identify_returns_identifier_result():
    identifier = HasheousIdentifier()
    await identifier.setup({})

    payload = {"name": "Super Mario World", "platform": "Super Nintendo (SNES)"}
    with aioresponses() as m:
        m.get(_HASH_URL, status=200, payload=payload)
        rom = _make_rom(sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709")
        result = await identifier.identify(rom)

    assert result is not None
    assert result.canonical_name == "Super Mario World"
    assert result.platform == "Super Nintendo (SNES)"
    assert result.provider == "hasheous"
    assert result.source_id == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    assert 0.0 < result.confidence <= 1.0

    assert isinstance(identifier, Identifier)

    await identifier.close()


@pytest.mark.asyncio
async def test_hasheous_identify_returns_none_on_404():
    identifier = HasheousIdentifier()
    await identifier.setup({})

    with aioresponses() as m:
        m.get(_HASH_URL, status=404)
        rom = _make_rom(sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709")
        result = await identifier.identify(rom)

    assert result is None

    await identifier.close()


@pytest.mark.asyncio
async def test_hasheous_identify_returns_none_when_no_hash():
    identifier = HasheousIdentifier()
    await identifier.setup({})

    rom = _make_rom()
    result = await identifier.identify(rom)

    assert result is None

    await identifier.close()
