"""Streaming CSV writer for run reports.

Writes one row per ROM with all columns defined in the spec.
Flushes every N rows for performance. Append-only during a run.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import TextIO

from multiscraper.models import ScrapedResult

CSV_COLUMNS = [
    "run_id", "row_seq", "system", "batch_id", "worker_id",
    "rom_relpath", "rom_raw_name", "rom_size", "rom_crc32", "rom_sha1",
    "identify_method", "status", "match_score", "chosen_provider",
    "fetched_at", "elapsed_ms", "error", "warnings",
    "name", "name_language",
    "desc", "desc_language", "desc_source",
    "genre", "genre_language", "genre_source",
    "releasedate", "developer", "publisher",
    "players", "rating",
    "image", "thumbnail", "video", "marquee", "box3d", "backcover",
    "fanart", "manual", "miximage", "logo",
    "total_media_ok", "total_media_bytes",
]

_MEDIA_TYPES = [
    "image", "thumbnail", "video", "marquee", "box3d", "backcover",
    "fanart", "manual", "miximage", "logo",
]


class CsvWriter:
    """Streaming CSV writer for run reports."""

    def __init__(self, path: Path, flush_every: int = 50):
        self._path = path
        self._flush_every = flush_every
        self._file: TextIO | None = None
        self._writer: csv.DictWriter[str] | None = None
        self._buffer_count = 0
        self._lock = asyncio.Lock()

    async def write_header(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(  # noqa: SIM115 - held open across async write_row calls
            self._path, "w", newline="", encoding="utf-8",
        )
        self._writer = csv.DictWriter(
            self._file, fieldnames=CSV_COLUMNS, lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        self._writer.writeheader()
        self._file.flush()

    async def write_row(
        self, run_id: str, row_seq: int, batch_id: int,
        worker_id: str, result: ScrapedResult,
    ) -> None:
        assert self._writer is not None
        async with self._lock:
            row = self._result_to_row(run_id, row_seq, batch_id, worker_id, result)
            self._writer.writerow(row)
            self._buffer_count += 1
            if self._buffer_count >= self._flush_every:
                assert self._file is not None
                self._file.flush()
                self._buffer_count = 0

    def _result_to_row(
        self, run_id: str, row_seq: int, batch_id: int,
        worker_id: str, result: ScrapedResult,
    ) -> dict[str, str]:
        rom = result.rom
        ri = rom.rom_id
        md = result.metadata

        media_by_type = {m.type.value: m for m in result.media}
        media_cells: dict[str, str] = {}
        total_ok = 0
        total_bytes = 0
        for mt in _MEDIA_TYPES:
            if mt in media_by_type:
                mf = media_by_type[mt]
                media_cells[mt] = f"OK:{mf.bytes}"
                total_ok += 1
                total_bytes += mf.bytes
            elif result.status.value in ("NO_MATCH", "SKIPPED", "BLOCKED"):
                media_cells[mt] = ""
            else:
                media_cells[mt] = "MISSING"

        return {
            "run_id": run_id,
            "row_seq": str(row_seq),
            "system": rom.system,
            "batch_id": str(batch_id),
            "worker_id": worker_id,
            "rom_relpath": ri.rel_path,
            "rom_raw_name": rom.raw_name,
            "rom_size": str(ri.size),
            "rom_crc32": ri.crc32 or "",
            "rom_sha1": ri.sha1 or "",
            "identify_method": result.identify_method.value,
            "status": result.status.value,
            "match_score": f"{result.match_score:.4f}" if result.match_score is not None else "",
            "chosen_provider": result.chosen_provider or "",
            "fetched_at": result.fetched_at.isoformat(),
            "elapsed_ms": str(result.elapsed_ms),
            "error": result.error or "",
            "warnings": ";".join(result.warnings) if result.warnings else "",
            "name": md.name if md else "",
            "name_language": "",
            "desc": md.desc if md and md.desc else "",
            "desc_language": "",
            "desc_source": "",
            "genre": md.genre if md and md.genre else "",
            "genre_language": "",
            "genre_source": "",
            "releasedate": (
                md.releasedate.strftime("%Y%m%dT%H%M%S")
                if md and md.releasedate else ""
            ),
            "developer": md.developer if md and md.developer else "",
            "publisher": md.publisher if md and md.publisher else "",
            "players": str(md.players) if md and md.players else "",
            "rating": f"{md.rating:.2f}" if md and md.rating is not None else "",
            **media_cells,
            "total_media_ok": str(total_ok),
            "total_media_bytes": str(total_bytes),
        }

    async def flush(self) -> None:
        if self._file is not None:
            self._file.flush()
        self._buffer_count = 0

    async def close(self) -> None:
        await self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None
        self._writer = None
