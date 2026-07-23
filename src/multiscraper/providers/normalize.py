"""ROM name normalization.

Strips region codes, version tags, GoodTools codes, No-Intro tags,
file extensions, and extra whitespace from ROM filenames to produce
a clean game title for provider search queries.
"""

from __future__ import annotations

import re

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.[a-zA-Z0-9]{1,4}$", re.IGNORECASE),
    re.compile(
        r"\s*\("
        r"(?:USA|U|Europe|EU|World|WOR|Japan|JP|Asia|ASIA"
        r"|En|Fr|De|It|Es|Pt|Jp|Zh|Ko|Multi|M\d"
        r"|Rev\s*[\w.]+|v[\d.]+"
        r"|Beta|Proto|Demo|Sample|Hack|Pirate|Unl"
        r"|SMW\s*Hack|SMB\s*Hack"
        r"|a\d|b\d|c\d|f\d|h\d|o\d|p\d|t\d|s\d"
        r"|!\+?|\+[a-zA-Z]"
        r")"
        r"\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*\["
        r"(?:!?\+?|a\d|b\d|c\d|f\d|h\d[\w]*|o\d|p\d|t\d|s\d"
        r"|T\+?[\w]*"
        r")"
        r"\]",
        re.IGNORECASE,
    ),
]


def normalize_rom_name(raw_name: str) -> str:
    """Normalize a ROM filename into a clean game title.

    Strips region codes, version tags, GoodTools/No-Intro tags,
    file extensions, and extra whitespace.

    Args:
        raw_name: The raw ROM filename (with or without extension).

    Returns:
        A clean game title suitable for provider search queries.
    """
    result = raw_name.strip()
    for pattern in _PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result
