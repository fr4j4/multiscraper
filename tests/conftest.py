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


def _patch_aioresponses_for_aiohttp_3_14() -> None:
    """Monkey-patch aioresponses.RequestMatch._build_response to provide a
    stream_writer when using aiohttp >= 3.11 (which made stream_writer a
    required keyword arg on ClientResponse). This shim is only needed for
    tests that use aioresponses with the in-tree aiohttp version.
    """
    try:
        import aiohttp
        import aioresponses.core as aio_core
        from aiohttp.base_protocol import BaseProtocol
        from aiohttp.client_reqrep import StreamWriter
    except ImportError:
        return

    if hasattr(aio_core.RequestMatch, "_stream_writer_patch_applied"):
        return

    orig = aio_core.RequestMatch._build_response

    class _DummyProto(BaseProtocol):
        def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
            super().__init__(loop=loop)

        async def write(self, *args: object, **kwargs: object) -> None:
            return None

        def write_eof(self) -> None:
            pass

    class _PatchedResponse(aiohttp.ClientResponse):
        def __init__(self, *args: object, **kwargs: object) -> None:
            if "stream_writer" not in kwargs or kwargs.get("stream_writer") is None:
                try:
                    real_loop = asyncio.get_running_loop()
                except RuntimeError:
                    real_loop = asyncio.new_event_loop()
                kwargs["stream_writer"] = StreamWriter(_DummyProto(real_loop), real_loop)
                kwargs["loop"] = real_loop
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _patched(
        self: object, *args: object, response_class: type | None = None, **kwargs: object
    ) -> object:
        if response_class is None:
            response_class = _PatchedResponse
        return orig(self, *args, response_class=response_class, **kwargs)

    aio_core.RequestMatch._build_response = _patched
    aio_core.RequestMatch._stream_writer_patch_applied = True


_patch_aioresponses_for_aiohttp_3_14()
