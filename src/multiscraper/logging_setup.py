"""Logging configuration for multiscraper.

Uses stdlib logging with a RichHandler for terminal output and a
FileHandler for JSONL file output. Library loggers are silenced
to WARNING by default; `-vv` raises them to INFO.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from rich.logging import RichHandler

_LIBRARY_LOGGERS = [
    "aiohttp",
    "asyncio",
    "asyncssh",
    "httpx",
    "urllib3",
    "vcr",
]


class JsonlFormatter(logging.Formatter):
    """Format log records as single-line JSON for run.log.jsonl."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(
    *,
    verbose: int = 0,
    quiet: bool = False,
    log_file: Path | None = None,
) -> None:
    """Configure logging for the multiscraper package.

    Args:
        verbose: 0=INFO, 1=DEBUG (multiscraper only), 2=DEBUG+libraries INFO.
        quiet: if True, set multiscraper to WARNING.
        log_file: if provided, write JSONL to this file.
    """
    if quiet:
        ms_level: int = logging.WARNING
    elif verbose >= 1:
        ms_level = logging.DEBUG
    else:
        ms_level = logging.INFO

    lib_level = logging.INFO if verbose >= 2 else logging.WARNING

    ms_logger = logging.getLogger("multiscraper")
    ms_logger.setLevel(ms_level)
    ms_logger.handlers.clear()

    terminal_handler = RichHandler(rich_tracebacks=True, show_path=False)
    terminal_handler.setLevel(ms_level)
    ms_logger.addHandler(terminal_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(ms_level)
        file_handler.setFormatter(JsonlFormatter())
        ms_logger.addHandler(file_handler)

    for lib in _LIBRARY_LOGGERS:
        logging.getLogger(lib).setLevel(lib_level)
