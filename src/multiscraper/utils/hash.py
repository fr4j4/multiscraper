"""Hash utilities for ROM identification.

CRC32 is the default hash (fast, accepted by ScreenScraper).
SHA1 is the fallback when CRC32 collides or a provider requires it.
"""

from __future__ import annotations

import hashlib
import zlib


def compute_crc32(data: bytes) -> str:
    """Compute CRC32 of data and return as 8-char lowercase hex string."""
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def compute_sha1(data: bytes) -> str:
    """Compute SHA1 of data and return as 40-char lowercase hex string."""
    return hashlib.sha1(data).hexdigest()
