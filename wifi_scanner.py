"""Platform-neutral entry points for native Wi-Fi scanning and privacy guidance."""

from __future__ import annotations

import platform
import webbrowser
from typing import Any

from macos_wifi import (
    LOCATION_STATUS_NAMES,
    location_authorization,
    request_location_authorization,
)


def scan_wifi() -> list[dict[str, Any]]:
    system = platform.system()
    if system == "Darwin":
        from macos_wifi import scan_wifi as scan_macos

        return scan_macos()
    if system == "Windows":
        from windows_wifi import scan_wifi as scan_windows

        return scan_windows()
    raise RuntimeError("Live Wi-Fi scanning is supported on macOS and Windows 11.")


def privacy_status() -> tuple[str, bool]:
    """Return user-facing privacy state and whether an access action is useful."""
    system = platform.system()
    if system == "Darwin":
        status, _ = location_authorization()
        return f"Location: {LOCATION_STATUS_NAMES.get(status, 'Unavailable')}", status == 0
    if system == "Windows":
        return "Location: controlled by Windows Privacy settings", True
    return "Location: unavailable on this platform", False


def request_privacy_access() -> tuple[str, Any | None]:
    system = platform.system()
    if system == "Darwin":
        _, manager = request_location_authorization()
        return "Respond to the macOS prompt, then restart the app", manager
    if system == "Windows":
        webbrowser.open("ms-settings:privacy-location")
        return (
            "Enable Location services and Let desktop apps access your location, then scan again",
            None,
        )
    return "Live Wi-Fi scanning is unavailable on this platform", None
