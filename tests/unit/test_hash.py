"""Tests for hash utilities."""

from multiscraper.utils.hash import compute_crc32, compute_sha1


def test_compute_crc32_known_value():
    data = b"hello world"
    result = compute_crc32(data)
    assert result == "0d4a1185"


def test_compute_crc32_empty():
    assert compute_crc32(b"") == "00000000"


def test_compute_sha1_known_value():
    data = b"hello world"
    result = compute_sha1(data)
    assert result == "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"


def test_compute_sha1_empty():
    result = compute_sha1(b"")
    assert result == "da39a3ee5e6b4b0d3255bfef95601890afd80709"


def test_crc32_returns_hex_lowercase():
    result = compute_crc32(b"test")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_sha1_returns_hex_lowercase():
    result = compute_sha1(b"test")
    assert len(result) == 40
    assert all(c in "0123456789abcdef" for c in result)
