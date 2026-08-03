"""Windows Native Wi-Fi scanning through wlanapi.dll.

The ctypes declarations live in this module so importing the shared UI remains safe on
macOS and Linux. Native calls are made only by :func:`scan_wifi` on Windows.
"""

from __future__ import annotations

import ctypes
import platform
import time
import uuid
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

DWORD = ctypes.c_uint32
ULONG = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
USHORT = ctypes.c_uint16
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPVOID = ctypes.c_void_p

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_NOT_SUPPORTED = 50
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_NDIS_DOT11_POWER_STATE_INVALID = 0x80342002
WLAN_CLIENT_VERSION_LONGHORN = 2
DOT11_BSS_TYPE_ANY = 3
WLAN_INTERFACE_STATE_NOT_READY = 0
# WlanScan completes asynchronously. This bounded fallback allows typical drivers to refresh their
# cache without blocking Qt's GUI thread because the entire scan runs in a worker.
SCAN_SETTLE_SECONDS = 4.0
MAX_WLAN_INTERFACES = 128
MAX_BSS_ENTRIES = 65_536


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __str__(self) -> str:
        raw = bytes(self)
        return str(uuid.UUID(bytes_le=raw))


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", wintypes.WCHAR * 256),
        ("isState", ctypes.c_int),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", DWORD),
        ("dwIndex", DWORD),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class WLAN_RATE_SET(ctypes.Structure):
    _fields_ = [
        ("uRateSetLength", ULONG),
        ("usRateSet", USHORT * 126),
    ]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", ULONG),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11BssType", ctypes.c_int),
        ("dot11BssPhyType", ctypes.c_int),
        ("lRssi", LONG),
        ("uLinkQuality", ULONG),
        ("bInRegDomain", ctypes.c_ubyte),
        ("usBeaconPeriod", USHORT),
        ("ullTimestamp", ctypes.c_ulonglong),
        ("ullHostTimestamp", ctypes.c_ulonglong),
        ("usCapabilityInformation", USHORT),
        ("ulChCenterFrequency", ULONG),
        ("wlanRateSet", WLAN_RATE_SET),
        ("ulIeOffset", ULONG),
        ("ulIeSize", ULONG),
    ]


class WLAN_BSS_LIST(ctypes.Structure):
    _fields_ = [
        ("dwTotalSize", DWORD),
        ("dwNumberOfItems", DWORD),
        ("wlanBssEntries", WLAN_BSS_ENTRY * 1),
    ]


def frequency_to_channel(frequency_khz: int) -> tuple[int | None, str]:
    """Map a BSS center frequency in kHz to channel and stable display band."""
    if frequency_khz <= 0:
        return None, "Unknown"
    mhz = frequency_khz / 1000
    if mhz == 2484:
        return 14, "2.4 GHz"
    if 2412 <= mhz <= 2472 and (mhz - 2407) % 5 == 0:
        return int((mhz - 2407) / 5), "2.4 GHz"
    if mhz == 5935:
        return 2, "6 GHz"
    if 5955 <= mhz <= 7115 and (mhz - 5950) % 5 == 0:
        return int((mhz - 5950) / 5), "6 GHz"
    if 4910 <= mhz <= 5895 and (mhz - 5000) % 5 == 0:
        return int((mhz - 5000) / 5), "5 GHz"
    if 2400 <= mhz < 2500:
        return None, "2.4 GHz"
    if 4900 <= mhz < 5925:
        return None, "5 GHz"
    if 5925 <= mhz <= 7125:
        return None, "6 GHz"
    return None, "Unknown"


def parse_bss_entry(entry: WLAN_BSS_ENTRY) -> dict[str, Any]:
    length = int(entry.dot11Ssid.uSSIDLength)
    if not 0 <= length <= len(entry.dot11Ssid.ucSSID):
        raise ValueError(f"Invalid DOT11 SSID length: {length}")
    ssid_bytes = bytes(entry.dot11Ssid.ucSSID[:length])
    ssid = ssid_bytes.decode("utf-8", errors="replace") if ssid_bytes else "<hidden>"
    bssid = ":".join(f"{byte:02X}" for byte in entry.dot11Bssid)
    channel, band = frequency_to_channel(int(entry.ulChCenterFrequency))
    rssi = int(entry.lRssi)
    if not -127 <= rssi <= 0:
        raise ValueError(f"Invalid RSSI value: {rssi}")
    return {
        "ssid": ssid,
        "bssid": bssid,
        "band": band,
        "rssi_dbm": rssi,
        "channel": channel,
    }


def _error_message(code: int, operation: str) -> str:
    if code == ERROR_ACCESS_DENIED:
        return (
            "Windows denied access to nearby Wi-Fi details. Open Settings → Privacy & security → "
            "Location, enable Location services and Let desktop apps access your location, then "
            "scan again. Administrator access does not bypass this privacy permission."
        )
    if code == ERROR_SERVICE_NOT_ACTIVE:
        return "The Windows WLAN AutoConfig service is not running. Start the WlanSvc service."
    if code == ERROR_NDIS_DOT11_POWER_STATE_INVALID:
        return "The Wi-Fi adapter radio is turned off. Enable Wi-Fi and try again."
    if code == ERROR_NOT_SUPPORTED:
        return "Windows Native Wi-Fi is unavailable; verify that WLAN AutoConfig is enabled."
    try:
        detail = ctypes.FormatError(code).strip()
    except (AttributeError, OSError):
        detail = "unknown Windows error"
    return f"{operation} failed ({code}): {detail}"


def _check(code: int, operation: str) -> None:
    if code != ERROR_SUCCESS:
        raise RuntimeError(_error_message(code, operation))


def _array_from_pointer(pointer: int, count: int, item_type: type[ctypes.Structure], offset: int):
    array_type = item_type * count
    return ctypes.cast(pointer + offset, ctypes.POINTER(array_type)).contents


def _validated_count(count: int, maximum: int, description: str) -> int:
    if not 0 <= count <= maximum:
        raise RuntimeError(f"Windows returned an invalid {description} count: {count}")
    return count


def _validate_bss_list_size(bss_list: WLAN_BSS_LIST) -> int:
    count = _validated_count(int(bss_list.dwNumberOfItems), MAX_BSS_ENTRIES, "Wi-Fi entry")
    required = WLAN_BSS_LIST.wlanBssEntries.offset + count * ctypes.sizeof(WLAN_BSS_ENTRY)
    if int(bss_list.dwTotalSize) < required:
        raise RuntimeError(
            "Windows returned a malformed Wi-Fi entry buffer "
            f"({int(bss_list.dwTotalSize)} bytes; at least {required} required)."
        )
    return count


def _configure_api(api: Any) -> None:
    api.WlanOpenHandle.argtypes = [
        DWORD,
        LPVOID,
        ctypes.POINTER(DWORD),
        ctypes.POINTER(HANDLE),
    ]
    api.WlanOpenHandle.restype = DWORD
    api.WlanCloseHandle.argtypes = [HANDLE, LPVOID]
    api.WlanCloseHandle.restype = DWORD
    api.WlanEnumInterfaces.argtypes = [
        HANDLE,
        LPVOID,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    api.WlanEnumInterfaces.restype = DWORD
    api.WlanScan.argtypes = [
        HANDLE,
        ctypes.POINTER(GUID),
        ctypes.POINTER(DOT11_SSID),
        LPVOID,
        LPVOID,
    ]
    api.WlanScan.restype = DWORD
    api.WlanGetNetworkBssList.argtypes = [
        HANDLE,
        ctypes.POINTER(GUID),
        ctypes.POINTER(DOT11_SSID),
        ctypes.c_int,
        BOOL,
        LPVOID,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    api.WlanGetNetworkBssList.restype = DWORD
    api.WlanFreeMemory.argtypes = [LPVOID]
    api.WlanFreeMemory.restype = None


def scan_wifi(
    *,
    api: Any | None = None,
    settle: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Scan every enabled Windows WLAN interface and return normalized BSS readings."""
    if platform.system() != "Windows" and api is None:
        raise RuntimeError("The Windows Wi-Fi scanner can run only on Windows.")
    api = api or ctypes.WinDLL("wlanapi.dll")  # type: ignore[attr-defined]
    _configure_api(api)
    negotiated = DWORD()
    handle = HANDLE()
    _check(
        api.WlanOpenHandle(
            WLAN_CLIENT_VERSION_LONGHORN, None, ctypes.byref(negotiated), ctypes.byref(handle)
        ),
        "Opening the Windows Wi-Fi service",
    )
    interface_pointer = ctypes.c_void_p()
    try:
        _check(
            api.WlanEnumInterfaces(handle, None, ctypes.byref(interface_pointer)),
            "Enumerating Wi-Fi adapters",
        )
        if not interface_pointer.value:
            raise RuntimeError("Windows did not return any Wi-Fi adapters.")
        interface_list = ctypes.cast(
            interface_pointer, ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)
        ).contents
        interface_count = _validated_count(
            int(interface_list.dwNumberOfItems), MAX_WLAN_INTERFACES, "Wi-Fi adapter"
        )
        interfaces = _array_from_pointer(
            interface_pointer.value,
            interface_count,
            WLAN_INTERFACE_INFO,
            WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset,
        )
        enabled = [item for item in interfaces if item.isState != WLAN_INTERFACE_STATE_NOT_READY]
        if not enabled:
            raise RuntimeError("No enabled Windows Wi-Fi adapter was found. Enable Wi-Fi first.")
        for interface in enabled:
            _check(
                api.WlanScan(handle, ctypes.byref(interface.InterfaceGuid), None, None, None),
                "Wi-Fi scan",
            )
        # WlanScan is asynchronous. This bounded wait occurs inside the application's worker thread.
        settle(SCAN_SETTLE_SECONDS)
        readings: list[dict[str, Any]] = []
        for interface in enabled:
            bss_pointer = ctypes.c_void_p()
            _check(
                api.WlanGetNetworkBssList(
                    handle,
                    ctypes.byref(interface.InterfaceGuid),
                    None,
                    DOT11_BSS_TYPE_ANY,
                    False,
                    None,
                    ctypes.byref(bss_pointer),
                ),
                f"Reading networks from {interface.strInterfaceDescription}",
            )
            try:
                if not bss_pointer.value:
                    continue
                bss_list = ctypes.cast(bss_pointer, ctypes.POINTER(WLAN_BSS_LIST)).contents
                entry_count = _validate_bss_list_size(bss_list)
                entries = _array_from_pointer(
                    bss_pointer.value,
                    entry_count,
                    WLAN_BSS_ENTRY,
                    WLAN_BSS_LIST.wlanBssEntries.offset,
                )
                for entry in entries:
                    try:
                        readings.append(parse_bss_entry(entry))
                    except ValueError:
                        # A malformed driver entry must not abort otherwise usable observations.
                        continue
            finally:
                if bss_pointer.value:
                    api.WlanFreeMemory(bss_pointer)
        strongest: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
        for reading in readings:
            key = (reading["ssid"], reading["bssid"], reading["band"], reading["channel"])
            if key not in strongest or reading["rssi_dbm"] > strongest[key]["rssi_dbm"]:
                strongest[key] = reading
        if not strongest:
            raise RuntimeError(
                "Windows returned no usable nearby Wi-Fi networks. Confirm Wi-Fi is enabled and "
                "that Windows itself can display nearby networks. Wait a few seconds and retry."
            )
        return list(strongest.values())
    finally:
        if interface_pointer.value:
            api.WlanFreeMemory(interface_pointer)
        api.WlanCloseHandle(handle, None)
