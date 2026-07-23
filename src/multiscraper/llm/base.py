"""TextGenerator Protocol for LLM-based text enhancement.

In v1, the default is NoOpTextGenerator (returns input unchanged).
The OpenAICompatTextGenerator is present but inactive.
In v2, activating it will enhance descriptions via an LLM.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class TextGenerator(Protocol):
    """Interface for text generation/enhancement via LLM."""

    async def generate_description(self, rom_meta: dict[str, str]) -> str:
        """Generate a description from ROM metadata."""
        ...

    async def enhance_text(
        self, text: str, kind: Literal["desc", "genre", "summary"],
    ) -> str:
        """Enhance an existing text field."""
        ...
