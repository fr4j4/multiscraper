"""Tests for es_systems.cfg parser."""

from pathlib import Path

from multiscraper.config.es_systems_parser import parse_es_systems


def test_parse_es_systems(tmp_path: Path):
    cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<systemList>
  <system>
    <name>snes</name>
    <fullname>Super Nintendo Entertainment System</fullname>
    <path>~/roms/snes</path>
    <extension>.smc .sfc .SMC .SFC</extension>
    <command>snesemulator %ROM%</command>
    <platform>snes</platform>
    <theme>snes</theme>
  </system>
  <system>
    <name>nes</name>
    <fullname>Nintendo Entertainment System</fullname>
    <path>~/roms/nes</path>
    <extension>.nes .NES</extension>
    <command>nesemulator %ROM%</command>
    <platform>nes</platform>
    <theme>nes</theme>
  </system>
</systemList>
"""
    cfg_path = tmp_path / "es_systems.cfg"
    cfg_path.write_text(cfg_content)

    systems = parse_es_systems(cfg_path)
    assert len(systems) == 2
    assert systems[0].name == "snes"
    assert systems[0].fullname == "Super Nintendo Entertainment System"
    assert systems[0].path == "~/roms/snes"
    assert ".smc" in systems[0].extensions
    assert ".sfc" in systems[0].extensions
    assert systems[0].platform == "snes"
    assert systems[1].name == "nes"
    assert systems[1].platform == "nes"


def test_parse_es_systems_empty(tmp_path: Path):
    cfg_content = """<?xml version="1.0" encoding="UTF-8"?>
<systemList>
</systemList>
"""
    cfg_path = tmp_path / "es_systems.cfg"
    cfg_path.write_text(cfg_content)

    systems = parse_es_systems(cfg_path)
    assert len(systems) == 0
