"""Core Location and CoreWLAN services, independent of either UI implementation."""

from __future__ import annotations

import platform
from typing import Any

LOCATION_AUTHORIZED = {3, 4}
LOCATION_STATUS_NAMES = {
    0: "Not requested",
    1: "Restricted",
    2: "Denied",
    3: "Authorized",
    4: "Authorized while in use",
}


def location_authorization() -> tuple[int | None, Any | None]:
    if platform.system() != "Darwin":
        return None, None
    try:
        from objc import loadBundle

        loadBundle(
            "CoreLocation",
            bundle_path="/System/Library/Frameworks/CoreLocation.framework",
            module_globals=globals(),
        )
        manager = CLLocationManager.alloc().init()  # noqa: F821
        return int(manager.authorizationStatus()), manager
    except Exception:
        return None, None


def request_location_authorization() -> tuple[int | None, Any | None]:
    status, manager = location_authorization()
    if manager is None or status != 0:
        return status, manager
    manager.requestWhenInUseAuthorization()
    return status, manager


def location_permission_error(status: int | None) -> str | None:
    if status in LOCATION_AUTHORIZED:
        return None
    if status == 0:
        return "Location access has not been granted. Request Location Access first."
    if status in {1, 2}:
        return (
            "Location access is denied. Enable WiFi Site Survey in System Settings → "
            "Privacy & Security → Location Services."
        )
    return "Core Location authorization could not be checked; SSID and BSSID cannot be read safely."


def normalize_band(value: Any) -> str:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = None
    return {1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}.get(numeric, "Unknown")


def scan_wifi() -> list[dict[str, Any]]:
    if platform.system() != "Darwin":
        raise RuntimeError("Live Wi-Fi scanning is available only on macOS.")
    permission_error = location_permission_error(location_authorization()[0])
    if permission_error:
        raise RuntimeError(permission_error)
    try:
        from objc import loadBundle

        loadBundle(
            "CoreWLAN",
            bundle_path="/System/Library/Frameworks/CoreWLAN.framework",
            module_globals=globals(),
        )
        client = CWWiFiClient.sharedWiFiClient()  # noqa: F821
        interface = client.interface()
        if interface is None:
            raise RuntimeError("CoreWLAN could not find a Wi-Fi interface.")
        networks, error = interface.scanForNetworksWithName_error_(None, None)
    except ImportError as exc:
        raise RuntimeError("PyObjC CoreWLAN support is missing.") from exc
    except Exception as exc:
        raise RuntimeError(f"CoreWLAN scan failed: {exc}") from exc
    if error is not None:
        raise RuntimeError(f"CoreWLAN scan failed: {error}")
    results, redacted = [], 0
    for network in networks or []:
        channel = network.wlanChannel()
        band = normalize_band(channel.channelBand()) if channel else "Unknown"
        ssid = str(network.ssid()) if network.ssid() is not None else "<hidden>"
        bssid = str(network.bssid()).upper() if network.bssid() is not None else "<unavailable>"
        redacted += int(network.ssid() is None and network.bssid() is None)
        results.append(
            {
                "ssid": ssid,
                "bssid": bssid,
                "band": band,
                "rssi_dbm": int(network.rssiValue()),
                "channel": int(channel.channelNumber()) if channel else None,
            }
        )
    if results and redacted == len(results):
        raise RuntimeError(
            "macOS redacted every SSID and BSSID. Re-authorize Location Services, quit, "
            "and reopen the app. Do not use sudo."
        )
    return results
