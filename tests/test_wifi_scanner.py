from __future__ import annotations

import sys
import types

import pytest

import wifi_scanner


def test_dispatches_windows_scanner_lazily(monkeypatch) -> None:
    expected = [{"ssid": "Office"}]
    fake = types.SimpleNamespace(scan_wifi=lambda: expected)
    monkeypatch.setitem(sys.modules, "windows_wifi", fake)
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Windows")
    assert wifi_scanner.scan_wifi() == expected


def test_dispatches_macos_scanner_lazily(monkeypatch) -> None:
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr("macos_wifi.scan_wifi", lambda: [{"ssid": "Mac"}])
    assert wifi_scanner.scan_wifi() == [{"ssid": "Mac"}]


def test_unsupported_scanner_is_clear(monkeypatch) -> None:
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="macOS and Windows 11"):
        wifi_scanner.scan_wifi()


def test_windows_privacy_action_opens_settings(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(wifi_scanner.webbrowser, "open", opened.append)
    label, enabled = wifi_scanner.privacy_status()
    message, manager = wifi_scanner.request_privacy_access()
    assert "Windows Privacy" in label
    assert enabled
    assert opened == ["ms-settings:privacy-location"]
    assert "desktop apps" in message
    assert manager is None
