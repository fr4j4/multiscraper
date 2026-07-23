"""Summary.json writer for run reports."""

from __future__ import annotations

import json
from pathlib import Path

from multiscraper.models import RunReport


def write_summary(report: RunReport, path: Path) -> None:
    """Write a RunReport to summary.json.

    Args:
        report: The RunReport to serialize.
        path: Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = report.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
