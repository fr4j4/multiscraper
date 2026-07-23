"""JSONL log writer for structured run events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlLogWriter:
    """Append-only JSONL log writer."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - held open across log_event calls

    def log_event(self, event: str, level: str = "INFO", **kwargs: Any) -> None:
        """Write a single log event as a JSON line."""
        entry = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "level": level,
            "event": event,
            **kwargs,
        }
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
