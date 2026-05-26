"""Updater unit tests — no network, no file ops outside tmp."""

from __future__ import annotations

import json
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from updater import (
    UpdateAvailable,
    _find_zip_asset,
    check_for_update,
    is_newer,
    parse_version,
)


def test_parse_version_strips_v_prefix():
    assert parse_version("v0.0.1") == (0, 0, 1)


def test_parse_version_strips_prerelease_suffix():
    assert parse_version("1.0.0-rc1") == (1, 0, 0)
    assert parse_version("1.0.0a1") == (1, 0, 0)


def test_parse_version_handles_short_strings():
    assert parse_version("2") == (2,)
    assert parse_version("0.9") == (0, 9)


def test_is_newer_ordering():
    assert is_newer("0.0.2", "0.0.1") is True
    assert is_newer("0.1.0", "0.0.99") is True
    assert is_newer("1.0.0", "0.99.99") is True


def test_is_newer_equal_or_older():
    assert is_newer("0.0.1", "0.0.1") is False
    assert is_newer("0.0.1", "0.0.2") is False
    assert is_newer("v1.0.0", "1.0.0") is False  # same after normalization


def test_find_zip_asset_prefers_named():
    assets = [
        {"name": "weird.txt", "browser_download_url": "https://x/y.txt"},
        {"name": "HollerBox.zip", "browser_download_url": "https://x/hb.zip"},
        {"name": "other.zip", "browser_download_url": "https://x/o.zip"},
    ]
    assert _find_zip_asset(assets) == "https://x/hb.zip"


def test_find_zip_asset_falls_back_to_any_zip():
    assets = [
        {"name": "other.zip", "browser_download_url": "https://x/o.zip"},
    ]
    assert _find_zip_asset(assets) == "https://x/o.zip"


def test_find_zip_asset_returns_none_when_no_zip():
    assert _find_zip_asset([{"name": "x.txt"}]) is None
    assert _find_zip_asset([]) is None


def _mock_release_response(payload: dict):
    """Build a context-manager mock for urlopen."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=lambda: json.dumps(payload).encode()))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_check_for_update_returns_record_when_newer():
    payload = {
        "tag_name": "v0.0.2",
        "html_url": "https://github.com/x/y/releases/v0.0.2",
        "body": "Release notes",
        "assets": [{"name": "HollerBox.zip", "browser_download_url": "https://gh/hb.zip"}],
    }
    with patch.object(urllib.request, "urlopen", return_value=_mock_release_response(payload)):
        out = check_for_update(current_version="0.0.1")
    assert isinstance(out, UpdateAvailable)
    assert out.latest == "0.0.2"
    assert out.current == "0.0.1"
    assert out.asset_url == "https://gh/hb.zip"


def test_check_for_update_returns_none_when_same():
    payload = {
        "tag_name": "v0.0.1",
        "assets": [{"name": "HollerBox.zip", "browser_download_url": "https://gh/hb.zip"}],
    }
    with patch.object(urllib.request, "urlopen", return_value=_mock_release_response(payload)):
        assert check_for_update(current_version="0.0.1") is None


def test_check_for_update_returns_none_when_no_asset():
    payload = {"tag_name": "v9.9.9", "assets": []}
    with patch.object(urllib.request, "urlopen", return_value=_mock_release_response(payload)):
        assert check_for_update(current_version="0.0.1") is None


def test_check_for_update_swallows_network_errors():
    def boom(*_a, **_kw):  # noqa: ANN002, ANN003
        raise TimeoutError("github unreachable")

    with patch.object(urllib.request, "urlopen", side_effect=boom):
        assert check_for_update(current_version="0.0.1") is None
