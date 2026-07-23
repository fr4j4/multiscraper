"""Tests for ROM name normalization."""

from multiscraper.providers.normalize import normalize_rom_name


def test_strips_region_parentheses():
    assert normalize_rom_name("Super Mario World (USA)") == "Super Mario World"


def test_strips_multiple_parentheses():
    assert normalize_rom_name("Final Fantasy (USA) (Rev 1)") == "Final Fantasy"


def test_strips_brackets():
    assert normalize_rom_name("Chrono Trigger [!]") == "Chrono Trigger"


def test_strips_version_tags():
    assert normalize_rom_name("Super Mario World (USA) (v1.1)") == "Super Mario World"


def test_strips_goodtools_codes():
    assert normalize_rom_name("Super Mario World (U) [!]") == "Super Mario World"


def test_strips_no_intro_tags():
    assert normalize_rom_name("Super Mario World (USA) (En)") == "Super Mario World"


def test_strips_extension():
    assert normalize_rom_name("Super Mario World.smc") == "Super Mario World"


def test_strips_extension_uppercase():
    assert normalize_rom_name("Super Mario World.SMC") == "Super Mario World"


def test_strips_extension_multiple():
    assert normalize_rom_name("Game.zip") == "Game"


def test_preserves_colons_in_name():
    assert normalize_rom_name("Link: The Faces of Evil (USA)") == "Link: The Faces of Evil"


def test_strips_leading_trailing_whitespace():
    assert normalize_rom_name("  Super Mario World  ") == "Super Mario World"


def test_strips_multip_region_codes():
    assert normalize_rom_name("Street Fighter II (World)") == "Street Fighter II"


def test_strips_rev_tags():
    assert normalize_rom_name("Game (Rev A)") == "Game"


def test_strips_hack_tags():
    assert normalize_rom_name("Super Mario World (SMW Hack)") == "Super Mario World"


def test_strips_demo_tags():
    assert normalize_rom_name("Game (Demo)") == "Game"


def test_strips_beta_tags():
    assert normalize_rom_name("Game (Beta)") == "Game"


def test_strips_proto_tags():
    assert normalize_rom_name("Game (Proto)") == "Game"


def test_strips_unl_tags():
    assert normalize_rom_name("Game (Unl)") == "Game"


def test_strips_pirate_tags():
    assert normalize_rom_name("Game (Pirate)") == "Game"


def test_complex_name():
    raw = "Super Mario World (USA) (Rev 1) [!] [a1]"
    assert normalize_rom_name(raw) == "Super Mario World"


def test_empty_string():
    assert normalize_rom_name("") == ""


def test_only_tags():
    assert normalize_rom_name("(USA)") == ""
