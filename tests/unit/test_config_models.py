"""Tests for new transport and system config models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiscraper.config.models import (
    OrchestratorConfig,
    System,
    SystemsConfig,
    Transport,
    TransportsConfig,
)


def test_transport_ssh_valid():
    t = Transport(
        name="arcade",
        kind="ssh",
        host="192.168.1.28",
        user="arcade",
        password="x",
        base_path="/home/arcade/ROMs",
    )
    assert t.name == "arcade"
    assert t.kind == "ssh"
    assert t.port == 22
    assert t.auto_trust is False
    assert t.base_path == "/home/arcade/ROMs"


def test_transport_local_valid():
    t = Transport(name="workstation", kind="local", base_path="/home/user/roms")
    assert t.kind == "local"
    assert t.base_path == "/home/user/roms"


def test_transport_local_with_empty_base_path_ok():
    t = Transport(name="root", kind="local", base_path="/")
    assert t.base_path == "/"


def test_transport_invalid_kind_fails():
    with pytest.raises(ValidationError):
        Transport(name="bad", kind="telepathy", base_path="/x")


def test_transport_invalid_name_pattern_fails():
    with pytest.raises(ValidationError):
        Transport(name="Bad-Name", kind="local", base_path="/x")


def test_transport_ssh_missing_host_fails():
    with pytest.raises(ValidationError) as excinfo:
        Transport(name="arcade", kind="ssh", user="arcade", base_path="/x")
    assert "host" in str(excinfo.value).lower()


def test_transport_ssh_missing_user_fails():
    with pytest.raises(ValidationError) as excinfo:
        Transport(name="arcade", kind="ssh", host="h", base_path="/x")
    assert "user" in str(excinfo.value).lower()


def test_transports_config_empty_list_fails():
    with pytest.raises(ValidationError) as excinfo:
        TransportsConfig(transports=[], current_transport="x")
    assert "empty" in str(excinfo.value).lower() or "non-empty" in str(excinfo.value).lower()


def test_transports_config_duplicate_names_fail():
    with pytest.raises(ValidationError) as excinfo:
        TransportsConfig(
            transports=[
                Transport(name="a", kind="local", base_path="/"),
                Transport(name="a", kind="local", base_path="/other"),
            ],
            current_transport="a",
        )
    assert "unique" in str(excinfo.value).lower()


def test_transports_config_current_transport_required():
    with pytest.raises(ValidationError):
        TransportsConfig(
            transports=[Transport(name="a", kind="local", base_path="/")],
        )


def test_transports_config_current_transport_unknown_fails():
    with pytest.raises(ValidationError) as excinfo:
        TransportsConfig(
            transports=[Transport(name="arcade", kind="local", base_path="/x")],
            current_transport="missing",
        )
    assert "missing" in str(excinfo.value)


def test_transports_config_current_transport_known_ok():
    cfg = TransportsConfig(
        transports=[Transport(name="arcade", kind="local", base_path="/x")],
        current_transport="arcade",
    )
    assert cfg.current_transport == "arcade"
    assert cfg.orchestrator.workers == 8
    assert cfg.defaults == {}


def test_transports_config_orchestrator_overridable():
    cfg = TransportsConfig(
        transports=[Transport(name="a", kind="local", base_path="/")],
        current_transport="a",
        orchestrator=OrchestratorConfig(workers=4),
    )
    assert cfg.orchestrator.workers == 4


def test_system_relative_path_only_ok():
    s = System(name="gba", relative_path="/gba", extensions=["gba"])
    assert s.relative_path == "/gba"
    assert s.full_path is None


def test_system_full_path_only_ok():
    s = System(name="psx", full_path="/mnt/external/roms/psx", extensions=["cue"])
    assert s.full_path == "/mnt/external/roms/psx"
    assert s.relative_path is None


def test_system_both_paths_fails():
    with pytest.raises(ValidationError) as excinfo:
        System(
            name="x",
            relative_path="/x",
            full_path="/y",
            extensions=["a"],
        )
    assert "one of" in str(excinfo.value).lower() or "only one" in str(excinfo.value).lower()


def test_system_no_paths_fails():
    with pytest.raises(ValidationError) as excinfo:
        System(name="x", extensions=["a"])
    assert "must have" in str(excinfo.value).lower() or "required" in str(excinfo.value).lower()


def test_system_empty_relative_path_fails():
    with pytest.raises(ValidationError) as excinfo:
        System(name="x", relative_path="", extensions=["a"])
    assert "empty" in str(excinfo.value).lower()


def test_system_empty_full_path_fails():
    with pytest.raises(ValidationError) as excinfo:
        System(name="x", full_path="", extensions=["a"])
    assert "empty" in str(excinfo.value).lower()


def test_system_invalid_name_pattern_fails():
    with pytest.raises(ValidationError):
        System(name="Bad-Name", relative_path="/x", extensions=["a"])


def test_systems_config_empty_list_ok():
    cfg = SystemsConfig(systems=[])
    assert cfg.systems == []


def test_systems_config_multiple_ok():
    cfg = SystemsConfig(
        systems=[
            System(name="snes", relative_path="/snes", extensions=["sfc"]),
            System(name="gba", relative_path="/gba", extensions=["gba"]),
        ]
    )
    assert len(cfg.systems) == 2
    assert cfg.systems[0].name == "snes"
