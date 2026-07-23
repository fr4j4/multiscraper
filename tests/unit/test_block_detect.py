"""Tests for block detection."""

from multiscraper.providers.block_detect import detect_blocked


def test_detect_cloudflare_403() -> None:
    body = b"<html><head><title>Just a moment...</title></head></html>"
    assert detect_blocked(403, body, {"cf-ray": "abc123"}) is True


def test_detect_cloudflare_503() -> None:
    body = b"Checking your browser before accessing.\n    <script>cf_chl_opt</script>"
    assert detect_blocked(503, body, {}) is True


def test_detect_captcha() -> None:
    body = b"<html>Please complete the captcha to continue</html>"
    assert detect_blocked(403, body, {}) is True


def test_detect_challenge_page() -> None:
    body = b"<html>Checking your browser before accessing"
    assert detect_blocked(503, body, {}) is True


def test_no_block_200() -> None:
    body = b"<html><body>Normal page</body></html>"
    assert detect_blocked(200, body, {}) is False


def test_no_block_404() -> None:
    body = b"<html><body>Not Found</body></html>"
    assert detect_blocked(404, body, {}) is False


def test_detect_rate_limit_429() -> None:
    body = b'{"error": "rate limited"}'
    assert detect_blocked(429, body, {}) is True


def test_detect_cf_ray_header() -> None:
    body = b"some content"
    assert detect_blocked(403, body, {"cf-ray": "123456-LAX"}) is True
