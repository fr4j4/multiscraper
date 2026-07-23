"""Tests for LibRetro Thumbnails provider (mocked HTTP HEAD probes)."""

import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.libretro_thumbnails import LibRetroThumbnailsProvider

_LR_URL = re.compile(r"https://raw\.githubusercontent\.com/libretro-thumbnails/.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_libretro_thumbnails_search_probes_urls():
    provider = LibRetroThumbnailsProvider()
    await provider.setup({})

    snap_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Snaps/Test_Game.png"
    )
    box_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Boxarts/Test_Game.png"
    )
    title_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Titles/Test_Game.png"
    )

    with aioresponses() as m:
        m.head(snap_url, status=200)
        m.head(box_url, status=200)
        m.head(title_url, status=404)
        m.head(
            re.compile(r".*Standard_Boxarts/.*"),
            status=404,
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].source_id != ""
    types = {ref.type for ref in candidates[0].media}
    assert MediaType.IMAGE in types
    assert MediaType.BOX3D in types

    await provider.close()


@pytest.mark.asyncio
async def test_libretro_thumbnails_fetch_media_from_candidate():
    provider = LibRetroThumbnailsProvider()
    await provider.setup({})

    snap_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Snaps/Test_Game.png"
    )
    box_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Boxarts/Test_Game.png"
    )
    title_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Named_Titles/Test_Game.png"
    )
    std_url = (
        "https://raw.githubusercontent.com/libretro-thumbnails/snes/master/"
        "Standard_Boxarts/Test_Game.png"
    )

    with aioresponses() as m:
        m.head(snap_url, status=200)
        m.head(box_url, status=200)
        m.head(title_url, status=200)
        m.head(std_url, status=200)
        rom = _make_rom()
        candidates = await provider.search(rom)

    media = await provider.fetch_media(
        candidates[0],
        {MediaType.IMAGE, MediaType.BOX3D, MediaType.LOGO},
    )

    assert MediaType.IMAGE in media
    assert MediaType.BOX3D in media
    assert MediaType.LOGO in media

    await provider.close()


@pytest.mark.asyncio
async def test_libretro_thumbnails_no_match_returns_empty():
    provider = LibRetroThumbnailsProvider()
    await provider.setup({})

    with aioresponses() as m:
        m.head(_LR_URL, status=404)
        m.head(_LR_URL, status=404)
        m.head(_LR_URL, status=404)
        m.head(_LR_URL, status=404)
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert candidates == []

    await provider.close()
