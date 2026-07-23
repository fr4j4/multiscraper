# Phase 0: Project Scaffold

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the project skeleton with `pyproject.toml`, directory structure, CLI entry point stub, logging setup, and a passing `pytest` collection.

**Depends on:** Nothing (foundation phase).

**Milestone:** `multiscraper --version` prints `0.1.0`; `pytest` runs and collects 0 tests with exit 0; `ruff check .` passes; `mypy --strict src/multiscraper` passes with no errors.

---

## Task 0.1: Create pyproject.toml and project structure

**Files:**
- Create: `pyproject.toml`
- Create: `src/multiscraper/__init__.py`
- Create: `src/multiscraper/__main__.py`
- Create: `src/multiscraper/cli.py`
- Create: `src/multiscraper/logging_setup.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`
- Create: `.editorconfig`
- Create: `LICENSE`
- Create: `README.md`
- Create: `CHANGELOG.md`

**Interfaces:**
- Produces: `multiscraper.cli:main` (entry point), `multiscraper.__version__` (str), `multiscraper.logging_setup:setup_logging` (callable)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/multiscraper/{config,core,transport,providers,output,llm,utils}
mkdir -p tests/{unit,integration,cassettes,fixtures}
mkdir -p config docs/{research,plans}
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "multiscraper"
version = "0.1.0"
description = "Parallel, multi-source scraper for retro gaming frontends"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "fr4j4"}]
keywords = ["emulationstation", "scraper", "retro", "gaming", "roms"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Games/Other Games",
    "Topic :: Multimedia :: Graphics",
]

dependencies = [
    "aiohttp>=3.9",
    "asyncssh>=2.13",
    "pydantic>=2.5",
    "click>=8.1",
    "rich>=13.6",
    "lxml>=5.0",
    "PyYAML>=6.0",
    "aiosqlite>=0.19",
    "aiofiles>=23.2",
    "charset-normalizer>=3.3",
    "python-ulid>=2.2",
    "Pillow>=10.0",
    "python-dateutil>=2.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "vcrpy>=5.1",
    "aioresponses>=0.7",
    "mypy>=1.8",
    "ruff>=0.3",
    "types-PyYAML",
    "types-aiofiles",
    "freezegun>=1.4",
]

[project.scripts]
multiscraper = "multiscraper.cli:main"

[project.entry-points."multiscraper.providers"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/multiscraper"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "network: requires internet access",
    "slow: long-running tests",
]
```

- [ ] **Step 3: Write src/multiscraper/__init__.py**

```python
"""multiscraper: parallel multi-source scraper for retro gaming frontends."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write src/multiscraper/__main__.py**

```python
"""Entry point for `python -m multiscraper`."""

from multiscraper.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Write src/multiscraper/cli.py**

```python
"""CLI entry point for multiscraper."""

import click

from multiscraper import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """multiscraper: parallel multi-source scraper for retro gaming frontends."""


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Write src/multiscraper/logging_setup.py**

```python
"""Logging configuration for multiscraper.

Uses stdlib logging with a RichHandler for terminal output and a
RotatingFileHandler for JSONL file output. Library loggers are silenced
to WARNING by default; `-vv` raises them to INFO.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from rich.logging import RichHandler

# Loggers from third-party libraries that we silence by default.
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
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
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

    # Configure multiscraper logger
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

    # Silence library loggers
    for lib in _LIBRARY_LOGGERS:
        logging.getLogger(lib).setLevel(lib_level)
```

- [ ] **Step 7: Write tests/conftest.py**

```python
"""Shared pytest fixtures for multiscraper tests."""

import asyncio
from collections.abc import AsyncGenerator

import pytest


@pytest.fixture
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 8: Write .gitignore**

```
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.cache/
.multiscraper_data/
reports/
.venv/
venv/
*.db
*.db-wal
*.db-shm
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/
.pytest_cache/
```

- [ ] **Step 9: Write .editorconfig**

```
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_style = space
indent_size = 4

[*.{yaml,yml}]
indent_style = space
indent_size = 2

[*.md]
trim_trailing_whitespace = false
```

- [ ] **Step 10: Write LICENSE (MIT)**

```text
MIT License

Copyright (c) 2026 fr4j4

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 11: Write README.md**

```markdown
# multiscraper

Parallel, multi-source scraper for retro gaming frontends (EmulationStation, RetroPie, Batocera, Recalbox).

## Quickstart

```bash
pip install -e ".[dev]"
multiscraper --version
```

## License

MIT
```

- [ ] **Step 12: Write CHANGELOG.md**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project scaffold with CLI entry point and logging setup.
```

- [ ] **Step 13: Write tests/__init__.py**

```python
```

- [ ] **Step 14: Install in dev mode and verify**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 15: Run milestone checks**

```bash
multiscraper --version
pytest --collect-only
ruff check .
mypy --strict src/multiscraper
```

Expected:
- `multiscraper --version` prints `multiscraper, version 0.1.0`
- `pytest --collect-only` exits 0 with "no tests collected"
- `ruff check .` exits 0
- `mypy --strict src/multiscraper` exits 0

- [ ] **Step 16: Commit**

```bash
git init
git add -A
git commit -m "feat: project scaffold with pyproject, CLI stub, logging setup"
```

---

## Milestone Gate

- [ ] `multiscraper --version` prints `0.1.0`
- [ ] `pytest --collect-only` exits 0
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes
- [ ] Git repo initialized with first commit