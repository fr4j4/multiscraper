# EmulationStation Files

`multiscraper` writes two kinds of files for EmulationStation (ES):

1. **`gamelist.xml`** per system, listing every matched ROM and its
   metadata.
2. **Media files** (cover, marquee, video, ...) under
   `media_root/<system>/`.

This document covers the structure, conventions, and the rules the
code follows.

## `gamelist.xml`

The XML generator is in
`src/multiscraper/output/gamelist_xml.py`. The format is documented
in spec Sección 2.4 and on
[GAMELISTS.md](https://github.com/RetroPie/EmulationStation/blob/master/GAMELISTS.md).

### Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<gameList>
  <game>
    <path>./Super Mario World (USA).smc</path>
    <name>Super Mario World</name>
    <desc>...</desc>
    <rating>0.95</rating>
    <releasedate>19901123T000000</releasedate>
    <developer>Nintendo</developer>
    <publisher>Nintendo</publisher>
    <genre>Platform</genre>
    <players>1</players>
    <sortname>Super Mario World</sortname>
    <image>./downloaded_images/snes/Super Mario World-image.jpg</image>
    <thumbnail>./downloaded_images/snes/Super Mario World-thumb.jpg</thumbnail>
    <video>./downloaded_images/snes/Super Mario World-video.mp4</video>
    <marquee>./downloaded_images/snes/Super Mario World-marquee.png</marquee>
  </game>
  <game>
    <path>./Mystery Game (USA).rom</path>
  </game>
</gameList>
```

### Rules the code follows

- **`<path>` is always present.** Even on `NO_MATCH` we emit a
  `<game>` with just the path so ES can still display the file.
- **Empty tags are omitted.** If `desc` is empty, the `<desc>`
  element is not written. ES fills in the rest.
- **`releasedate` format is `%Y%m%dT%H%M%S`.** Example: 23 November
  1990 00:00:00 is `19901123T000000`. The conversion lives in
  `gamelist_xml.py`:

  ```python
  md.releasedate.strftime("%Y%m%dT%H%M%S")
  ```

- **Media paths are relative to the system path.** The XML is
  written as `./downloaded_images/<system>/<rom>-<type>.<ext>`.
  In practice the `media_root` is also expected to be reachable
  from the system path under `downloaded_images/<system>/`.

- **Encoding is UTF-8.** `xml_declaration=True` and pretty-print
  with two-space indent are enforced by `minidom.toprettyxml`.

- **XML escaping is via `xml.sax.saxutils.escape`** (delegated by
  `ET.tostring`).

- **One file per system.** Output path is
  `gamelists/<system>/gamelist.xml` (the `gamelists` root is
  configurable via `convert-to-es --out`).

### Field reference

| XML tag | Source | Notes |
|---|---|---|
| `<path>` | `Rom.rom_id.rel_path` | Always present. |
| `<name>` | `GameMetadata.name` | Required when present. |
| `<desc>` | `GameMetadata.desc` | Omitted if empty. |
| `<rating>` | `GameMetadata.rating` | Float, two decimals. |
| `<releasedate>` | `GameMetadata.releasedate` | `YYYYMMDDTHHMMSS`. |
| `<developer>` | `GameMetadata.developer` | Omitted if empty. |
| `<publisher>` | `GameMetadata.publisher` | Omitted if empty. |
| `<genre>` | `GameMetadata.genre` | Omitted if empty. |
| `<players>` | `GameMetadata.players` | Integer, omitted if absent. |
| `<sortname>` | `GameMetadata.sortname` | Omitted if empty. |
| `<image>` | downloaded `MediaFile` (type=`image`) | Relative path. |
| `<thumbnail>` | downloaded `MediaFile` (type=`thumbnail`) | Relative path. |
| `<video>` | downloaded `MediaFile` (type=`video`) | Relative path. |
| `<marquee>` | downloaded `MediaFile` (type=`marquee`) | Relative path. |
| `<box3d>` | downloaded `MediaFile` (type=`box3d`) | Relative path. |
| `<backcover>` | downloaded `MediaFile` (type=`backcover`) | Relative path. |
| `<fanart>` | downloaded `MediaFile` (type=`fanart`) | Relative path. |
| `<manual>` | downloaded `MediaFile` (type=`manual`) | Relative path. |
| `<miximage>` | downloaded `MediaFile` (type=`miximage`) | Relative path. |
| `<logo>` | downloaded `MediaFile` (type=`logo`) | Relative path. |

If a `MediaType` was not downloaded, the corresponding tag is
absent from the `<game>` element.

### `NO_MATCH` rendering

When a ROM cannot be matched against any provider, the
`ScrapedResult` has `status=NO_MATCH` and `metadata=None`. The
generator still emits a `<game>` element with only the `<path>`
tag. ES renders the file with no metadata — the user can fix the
match manually with `multiscraper override add <path>` and re-run.

## Media files

### Naming convention

Pattern: `<normalized_name>-<type>.<ext>` (spec Sección 2.5).

Normalization rules, applied in order:

1. Strip characters not in the safe set: drop `< > : " / \ | ? *`
   and control characters.
2. Replace runs of whitespace with a single `_`.
3. Trim leading and trailing `_` and `.`.
4. **Collisions** — if a sibling file with the same name already
   exists, append `_<crc32[:6]>` before the type. Example:
   `Super_Mario_World_a1b2c3-image.png`.
5. **Case-insensitive filesystems** (Windows, default macOS) —
   add a numeric suffix `_1`, `_2`, etc. to keep names unique.

### Type suffix table

| `MediaType` | Suffix | Accepted extensions | Preferred |
|---|---|---|---|
| `image` | `-image` | `.png`, `.jpg`, `.jpeg`, `.webp` | `.jpg` |
| `thumbnail` | `-thumb` | `.png`, `.jpg` | `.jpg` |
| `video` | `-video` | `.mp4`, `.webm` | `.mp4` |
| `marquee` | `-marquee` | `.png`, `.jpg` | `.png` |
| `box3d` | `-3dbox` | `.png`, `.jpg` | `.png` |
| `backcover` | `-backcover` | `.png`, `.jpg` | `.jpg` |
| `fanart` | `-fanart` | `.png`, `.jpg` | `.jpg` |
| `manual` | `-manual` | `.pdf` | `.pdf` |
| `miximage` | `-miximage` | `.png`, `.jpg` | `.png` |
| `logo` | `-logo` | `.png` | `.png` |

The provider returns the actual file extension; the suffix table
above is used to filter and rank. A request for `image` will
accept `.png` from a provider if `.jpg` is not available.

### Location

Default (spec decisión #24):

```
$HOME/multiscraper_data/media/
  <system>/
    Super_Mario_World-image.jpg
    Super_Mario_World-thumb.jpg
    Super_Mario_World-video.mp4
    Super_Mario_World-marquee.png
```

Configurable:

- In `systems.yaml`: `media_root: /mnt/external/media`
- On the CLI: `multiscraper scrape --media-root /mnt/external/media`

The SQLite `media.local_path` column stores paths **relative to
`media_root`** for portability between machines (spec Sección 2.5).
The XML generator converts them back to the `./downloaded_images/...`
form expected by ES, which assumes a sibling folder under the
system path.

### Atomicity and partial writes

Media is downloaded to `<dest>.part` first, then renamed via
`aiofiles.os.replace` once the stream completes. If a worker is
killed mid-download (SIGTERM, `TIMED_OUT`), the `.part` file is
unlinked in the `finally` block so the next run starts fresh.

## `es_systems.cfg` discovery

`multiscraper` reads `es_systems.cfg` to know which systems exist
and where their ROMs are. The parser is in
`src/multiscraper/config/es_systems_parser.py`.

Search order (auto-discovered when `--es-systems` is not given):

1. `./es_systems.cfg`
2. `$HOME/.emulationstation/es_systems.cfg`
3. `~/.emulationstation/es_systems.cfg`
4. `config/es_systems.cfg`

A minimal `es_systems.cfg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<systemList>
    <system>
        <name>snes</name>
        <fullname>Super Nintendo</fullname>
        <path>~/RetroPie/roms/snes</path>
        <extension>.smc .sfc .fig</extension>
        <command>retroarch -L /opt/retropie/libretrocores/snes_libretro.so %ROM%</command>
        <platform>snes</platform>
        <theme>snes</theme>
    </system>
</systemList>
```

The parser extracts the `<name>`, `<fullname>`, `<path>`,
`<extension>`, `<command>`, `<platform>`, and `<theme>` fields.
`<extension>` is split on whitespace.

`multiscraper` only cares about `<name>`, `<path>`, `<extension>`,
and `<platform>`. The `<command>` and `<theme>` fields are read
but not used; the front end reads them itself.
