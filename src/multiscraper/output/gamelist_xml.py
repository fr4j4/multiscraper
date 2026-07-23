"""Generator for EmulationStation gamelist.xml files.

Produces XML compatible with ES: paths relative to system path,
releasedate in %Y%m%dT%H%M%S format, empty tags omitted.
"""

from __future__ import annotations

from xml.dom import minidom
from xml.etree import ElementTree as ET

from multiscraper.models import MediaType, ScrapedResult

_MEDIA_TAG_MAP = {
    MediaType.IMAGE: "image",
    MediaType.THUMBNAIL: "thumbnail",
    MediaType.VIDEO: "video",
    MediaType.MARQUEE: "marquee",
    MediaType.BOX3D: "box3d",
    MediaType.BACKCOVER: "backcover",
    MediaType.FANART: "fanart",
    MediaType.MANUAL: "manual",
    MediaType.MIXIMAGE: "miximage",
    MediaType.LOGO: "logo",
}


def generate_gamelist(results: list[ScrapedResult], system: str) -> str:
    """Generate a gamelist.xml string for a system.

    Args:
        results: List of ScrapedResult for this system.
        system: System name (unused in output, but for context).

    Returns:
        Pretty-printed XML string with <gameList> root.
    """
    root = ET.Element("gameList")

    for result in results:
        game_elem = ET.SubElement(root, "game")
        rom = result.rom
        ri = rom.rom_id

        ET.SubElement(game_elem, "path").text = ri.rel_path

        md = result.metadata
        if md:
            ET.SubElement(game_elem, "name").text = md.name
            if md.desc:
                ET.SubElement(game_elem, "desc").text = md.desc
            if md.rating is not None:
                ET.SubElement(game_elem, "rating").text = f"{md.rating:.2f}"
            if md.releasedate:
                ET.SubElement(game_elem, "releasedate").text = (
                    md.releasedate.strftime("%Y%m%dT%H%M%S")
                )
            if md.developer:
                ET.SubElement(game_elem, "developer").text = md.developer
            if md.publisher:
                ET.SubElement(game_elem, "publisher").text = md.publisher
            if md.genre:
                ET.SubElement(game_elem, "genre").text = md.genre
            if md.players is not None:
                ET.SubElement(game_elem, "players").text = str(md.players)
            if md.sortname:
                ET.SubElement(game_elem, "sortname").text = md.sortname

        for mf in result.media:
            tag_name = _MEDIA_TAG_MAP.get(mf.type)
            if tag_name:
                media_path = f"./downloaded_images/{system}/{mf.local_path}"
                ET.SubElement(game_elem, tag_name).text = media_path

    rough = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough)
    return dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
