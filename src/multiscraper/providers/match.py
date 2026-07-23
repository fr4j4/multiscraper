"""Match scoring between ROM names and candidate game names.

Uses a combination of normalized string similarity (difflib SequenceMatcher)
and heuristics (article removal, case folding).
"""

from __future__ import annotations

from difflib import SequenceMatcher


def _normalize(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip articles, collapse spaces."""
    result = name.lower().strip()
    for article in ("the ", "a ", "an "):
        if result.startswith(article):
            result = result[len(article):]
    result = " ".join(result.split())
    return result


def compute_match_score(rom_name: str, candidate_name: str) -> float:
    """Compute a match score between a ROM name and a candidate game name.

    Args:
        rom_name: Normalized ROM name (from normalize_rom_name).
        candidate_name: Game name from a provider.

    Returns:
        Score between 0.0 (no match) and 1.0 (exact match).
    """
    if not rom_name or not candidate_name:
        return 0.0

    norm_rom = _normalize(rom_name)
    norm_cand = _normalize(candidate_name)

    if norm_rom == norm_cand:
        return 1.0

    if norm_rom in norm_cand:
        ratio = len(norm_rom) / len(norm_cand)
        return max(0.75, ratio)

    if norm_cand in norm_rom:
        ratio = len(norm_cand) / len(norm_rom)
        return max(0.75, ratio)

    ratio = SequenceMatcher(None, norm_rom, norm_cand).ratio()
    return ratio
