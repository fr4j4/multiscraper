"""Block detection for Cloudflare, captcha, and rate limiting.

Providers use this to determine if a response indicates the source
is blocking us (Cloudflare challenge, captcha, 429 rate limit).
"""
from __future__ import annotations

_BLOCKING_STATUSES = {403, 503, 429}

_BLOCK_SIGNALS = [
    b"cloudflare",
    b"cf-ray",
    b"cf_chl_opt",
    b"captcha",
    b"challenge",
    b"just a moment",
    b"checking your browser",
    b"are you human",
    b"ddg_captcha",
]


def detect_blocked(status: int, body: bytes, headers: dict[str, str]) -> bool:
    """Detect if a response indicates blocking (Cloudflare, captcha, rate limit).

    Args:
        status: HTTP status code.
        body: Response body (bytes).
        headers: Response headers.

    Returns:
        True if the response indicates blocking, False otherwise.
    """
    if status not in _BLOCKING_STATUSES:
        return False

    for key, _val in headers.items():
        if key.lower() in ("cf-ray", "cf-mitigated"):
            return True

    body_lower = body.lower()[:2000]
    for signal in _BLOCK_SIGNALS:
        if signal in body_lower:
            return True

    return status == 429
