"""Parser for EmulationStation es_systems.cfg XML files."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pydantic import BaseModel


class SystemConfig(BaseModel):
    """A single system entry from es_systems.cfg."""

    name: str
    fullname: str = ""
    path: str = ""
    extensions: list[str] = []
    command: str = ""
    platform: str = ""
    theme: str = ""


def parse_es_systems(path: Path) -> list[SystemConfig]:
    """Parse an es_systems.cfg XML file.

    Args:
        path: Path to the es_systems.cfg file.

    Returns:
        List of SystemConfig entries.

    Raises:
        FileNotFoundError: if path does not exist.
        etree.XMLSyntaxError: if XML is malformed.
    """
    tree = etree.parse(str(path))
    root = tree.getroot()

    systems: list[SystemConfig] = []
    for sys_elem in root.findall("system"):
        name = _text(sys_elem, "name")
        if not name:
            continue

        ext_str = _text(sys_elem, "extension")
        extensions = ext_str.split() if ext_str else []

        systems.append(
            SystemConfig(
                name=name,
                fullname=_text(sys_elem, "fullname"),
                path=_text(sys_elem, "path"),
                extensions=extensions,
                command=_text(sys_elem, "command"),
                platform=_text(sys_elem, "platform"),
                theme=_text(sys_elem, "theme"),
            )
        )

    return systems


def _text(parent: etree._Element, tag: str) -> str:
    """Get text content of a child element, or empty string."""
    elem = parent.find(tag)
    return elem.text if elem is not None and elem.text else ""
