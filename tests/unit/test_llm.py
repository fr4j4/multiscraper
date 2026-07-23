"""Tests for LLM TextGenerator hook."""

import pytest

from multiscraper.llm.base import TextGenerator
from multiscraper.llm.noop import NoOpTextGenerator


@pytest.mark.asyncio
async def test_noop_returns_input_unchanged():
    gen = NoOpTextGenerator()
    result = await gen.generate_description({"name": "Test Game"})
    assert result == "Test Game"


@pytest.mark.asyncio
async def test_noop_enhance_text_returns_input():
    gen = NoOpTextGenerator()
    result = await gen.enhance_text("A test game.", "desc")
    assert result == "A test game."


def test_noop_satisfies_protocol():
    gen = NoOpTextGenerator()
    assert isinstance(gen, TextGenerator)
