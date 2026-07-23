# EmulationStation — Research Notes

`multiscraper` writes files that EmulationStation (ES) consumes.
This document summarises the upstream contracts: how ES discovers
systems, how it scrapes metadata when no external tool has done it
yet, and the exact structure it expects for `gamelist.xml` and
media folders.

References are from the spec's Apéndice B.

## Upstream projects

- [RetroPie EmulationStation](https://github.com/RetroPie/EmulationStation)
  — the reference fork used by RetroPie, Batocera, and Recalbox.
- [GAMELISTS.md](https://github.com/RetroPie/EmulationStation/blob/master/GAMELISTS.md)
  — canonical `gamelist.xml` spec.
- [SYSTEMS.md](https://github.com/RetroPie/EmulationStation/blob/master/SYSTEMS.md)
  — canonical `es_systems.cfg` spec.
- [ScreenScraper.cpp](https://github.com/RetroPie/EmulationStation/blob/master/es-app/src/scrapers/ScreenScraper.cpp)
  — the in-tree ScreenScraper scraper. Useful as a reference for
  the field mapping that ES itself uses, so that
  `multiscraper`'s output is consistent with what ES would
  produce.
- [GamesDBJSONScraperResources.cpp](https://github.com/RetroPie/EmulationStation/blob/master/es-app/src/scrapers/GamesDBJSONScraperResources.cpp)
  — the in-tree TheGamesDB scraper; reference for the field names
  TheGamesDB v2 returns.

## How ES discovers systems

ES reads a single XML file at startup:
`~/.emulationstation/es_systems.cfg` (path configurable via
`--es-systems` on the ES CLI). The root element is `<systemList>`
and each child `<system>` declares one system.

Each `<system>` has these children (per SYSTEMS.md):

- `<name>` — short identifier used in the URL path. Required.
- `<fullname>` — human-readable name shown in menus.
- `<path>` — folder where the ROMs live. ES scans this folder
  recursively.
- `<extension>` — space-separated list of accepted file
  extensions. Case-insensitive.
- `<command>` — shell command to launch the game. The literal
  `%ROM%` is replaced with the ROM path.
- `<platform>` — used for the ScreenScraper API call.
- `<theme>` — folder under `~/.emulationstation/themes/<theme>/`
  to use for art.

`multiscraper` parses the same file in
`src/multiscraper/config/es_systems_parser.py` and reuses the
`<name>`, `<path>`, `<extension>`, and `<platform>` fields. The
`<command>` and `<theme>` fields are read but not used.

## How ES scrapes (when no tool has run)

ES has built-in scrapers: ScreenScraper, TheGamesDB, and
ArcadeDB. They run when the user selects "scraper" inside the
ES UI. The implementations are the
`es-app/src/scrapers/*Scraper.cpp` files in the RetroPie fork.

ES scrapers work by:

1. Walking the `<path>` for each enabled system.
2. Hashing each file (CRC32 or SHA1, depending on the platform's
   scraper settings).
3. Querying the provider with the hash.
4. Asking the user to pick the best result (or auto-picking by
   match score).
5. Writing the result to `gamelist.xml` and the media to a
   `downloaded_images/<system>/` folder next to the system path.

`multiscraper` reproduces the data-side of this flow but with a
wider provider set, in batch, and without an interactive UI.

## `gamelist.xml` (the contract)

Source: [GAMELISTS.md](https://github.com/RetroPie/EmulationStation/blob/master/GAMELISTS.md).

### Root

```xml
<gameList>
  ...
</gameList>
```

Encoding: UTF-8. Declaration is optional but conventional. ES
tolerates both.

### `<game>` children

| Tag | Type | Notes |
|---|---|---|
| `<path>` | str, required | Relative to the system `<path>`. Always written by `multiscraper`. |
| `<name>` | str | Title shown in the ES UI. |
| `<desc>` | str | Long description. |
| `<rating>` | float | 0.0–1.0. ES multiplies by 5 for the visual star display. |
| `<releasedate>` | `YYYYMMDDTHHMMSS` | ISO basic format, no separators. |
| `<developer>` | str | |
| `<publisher>` | str | |
| `<genre>` | str | |
| `<players>` | int | |
| `<sortname>` | str | Optional; if absent, ES sorts by `<name>`. |
| `<image>` | path | Cover art. |
| `<thumbnail>` | path | Smaller box art / screenshot. |
| `<video>` | path | Video preview, MP4 or WEBM. |
| `<marquee>` | path | Logo / marquee image. |
| `<box3d>` | path | 3D box render. |
| `<backcover>` | path | Back of the box. |
| `<fanart>` | path | Fanart / background. |
| `<manual>` | path | PDF manual. |
| `<miximage>` | path | Composite image. |
| `<logo>` | path | Clear-logo style. |

Tags that are absent are filled in by ES with defaults from the
ROM filename. Tags that are present but empty are treated as
absent.

### Path convention

The XML file is at `<system path>/gamelist.xml`. The `path` tag
inside each `<game>` is relative to that location. Media is at
`<system path>/downloaded_images/<system>/...` by ES convention,
so the relative path from `gamelist.xml` to a media file is
`./downloaded_images/<system>/<rom>-<type>.<ext>`.

`multiscraper` follows this convention in
`output/gamelist_xml.py`:

```python
media_path = f"./downloaded_images/{system}/{mf.local_path}"
```

The `media_root` on disk does not need to be at
`downloaded_images/...`; the user points the front end at the
system folder and ES resolves the relative path itself.

## Media folder convention

ES loads media from the relative path in `gamelist.xml`. The
default location is `downloaded_images/<system>/` next to
`gamelist.xml`. Each file is named:

```
<rom_stem>-<type>.<ext>
```

Where `<type>` is one of: `image`, `thumb`, `video`, `marquee`,
`3dbox`, `backcover`, `fanart`, `manual`, `miximage`, `logo`.

`multiscraper` uses the same suffixes (see
`docs/ems_files.md` for the full table) and stores the files
under `media_root/<system>/<rom_stem>-<type>.<ext>`. The XML
emitter re-prefixes them with `./downloaded_images/<system>/` so
ES finds them.

## Auto-trust and permissions

When ES starts, it asks the user to trust the userdata folder on
first launch. The same applies to media files: ES reads any
file that the user can read. The XML emitter is therefore not
required to set any specific permission on the produced files.

## Other ES derivatives

`multiscraper` is written for the RetroPie fork, which is the
upstream of Batocera and Recalbox. Pegasus-frontend has a
different scraper contract; support is post-v1 in the spec
(Sección 6.9).

## Field-mapping references

When `multiscraper` queries ScreenScraper, it relies on the
same media-type naming as the in-tree `ScreenScraper.cpp`. The
table in `docs/ems_files.md` mirrors the constants in that file
(`box2D`, `ss`, `video`, `wheel`, `box-3D`, etc.).
