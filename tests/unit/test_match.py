"""Tests for match scoring."""

from multiscraper.providers.match import compute_match_score


def test_exact_match() -> None:
    assert compute_match_score("Super Mario World", "Super Mario World") == 1.0


def test_case_insensitive_match() -> None:
    assert compute_match_score("super mario world", "Super Mario World") == 1.0


def test_partial_match() -> None:
    score: float = compute_match_score("Super Mario World", "Super Mario World 2")
    assert 0.5 < score < 1.0


def test_no_match() -> None:
    score: float = compute_match_score("Super Mario World", "Final Fantasy")
    assert score < 0.3


def test_empty_strings() -> None:
    assert compute_match_score("", "") == 0.0


def test_subtitle_match() -> None:
    score: float = compute_match_score("Super Mario World", "Super Mario World: The Lost Levels")
    assert score > 0.7


def test_the_removal() -> None:
    score: float = compute_match_score("Legend of Zelda", "The Legend of Zelda")
    assert score > 0.9
