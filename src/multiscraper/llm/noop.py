"""NoOpTextGenerator: default implementation that returns input unchanged."""

from __future__ import annotations

from typing import Literal


class NoOpTextGenerator:
    """Default TextGenerator that does nothing (returns input unchanged)."""

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Return the game name as-is (no LLM in v1)."""
        return rom_meta.get("name", "")

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Return the text unchanged."""
        return text
