"""Shared pytest fixtures for multiscraper tests."""

import asyncio
from collections.abc import AsyncGenerator

import pytest


@pytest.fixture
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
