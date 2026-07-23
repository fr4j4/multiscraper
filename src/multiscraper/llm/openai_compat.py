"""OpenAI-compatible TextGenerator (inactive in v1).

This implementation is present for architectural completeness.
It will be activated in v2 when LLM enhancement is enabled.
Requires: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL env vars.
"""

from __future__ import annotations

import os
from typing import Literal


class OpenAICompatTextGenerator:
    """LLM text generator using an OpenAI-compatible API.

    INACTIVE in v1. To activate in v2:
    1. Set env vars: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    2. Set `text_generator: openai` in sources.yaml
    3. The orchestrator will use this instead of NoOpTextGenerator.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Generate a description via LLM. NOT IMPLEMENTED in v1."""
        raise NotImplementedError("OpenAICompatTextGenerator is inactive in v1")

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Enhance text via LLM. NOT IMPLEMENTED in v1."""
        raise NotImplementedError("OpenAICompatTextGenerator is inactive in v1")
