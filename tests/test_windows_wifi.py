from __future__ import annotations

import ctypes

import pytest

import windows_wifi
from windows_wifi import (
    WLAN_BSS_ENTRY,
    WLAN_BSS_LIST,
    WLAN_INTERFACE_INFO_LIST,
    frequency_to_channel,
    parse_bss_entry,
)


class FakeFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeWlanApi:
    def __init__(self) -> None:
        self.interfaces = WLAN_INTERFACE_INFO_LIST()
        self.interfaces.dwNumberOfItems = 1
        self.interfaces.InterfaceInfo[0].isState = 1
        self.interfaces.InterfaceInfo[0].strInterfaceDescription = "Test Wi-Fi"
        self.bss = WLAN_BSS_LIST()
        self.bss.dwTotalSize = ctypes.sizeof(WLAN_BSS_LIST)
        self.bss.dwNumberOfItems = 1
        entry = self.bss.wlanBssEntries[0]
        entry.dot11Ssid.uSSIDLength = 4
        entry.dot11Ssid.ucSSID[:4] = b"Test"
        entry.dot11Bssid[:] = bytes.fromhex("001122334455")
        entry.lRssi = -48
        entry.ulChCenterFrequency = 5_180_000
        self.freed = []
        self.closed = False
        self.WlanOpenHandle = FakeFunction(self.open_handle)
        self.WlanCloseHandle = FakeFunction(self.close_handle)
        self.WlanEnumInterfaces = FakeFunction(self.enum_interfaces)
        self.WlanScan = FakeFunction(lambda *args: windows_wifi.ERROR_SUCCESS)
        self.WlanGetNetworkBssList = FakeFunction(self.get_bss_list)
        self.WlanFreeMemory = FakeFunction(self.free_memory)

    def open_handle(self, version, reserved, negotiated, handle) -> int:
        ctypes.cast(negotiated, ctypes.POINTER(windows_wifi.DWORD))[0] = 2
        ctypes.cast(handle, ctypes.POINTER(windows_wifi.HANDLE))[0] = 123
        return windows_wifi.ERROR_SUCCESS

    def close_handle(self, handle, reserved) -> int:
        self.closed = True
        return windows_wifi.ERROR_SUCCESS

    def enum_interfaces(self, handle, reserved, output) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(self.interfaces)
        return windows_wifi.ERROR_SUCCESS

    def get_bss_list(self, *args) -> int:
        ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(self.bss)
        return windows_wifi.ERROR_SUCCESS

    def free_memory(self, pointer) -> None:
        self.freed.append(pointer.value if hasattr(pointer, "value") else int(pointer))


@pytest.mark.parametrize(
    ("frequency", "channel", "band"),
    [
        (2_412_000, 1, "2.4 GHz"),
        (2_472_000, 13, "2.4 GHz"),
        (2_484_000, 14, "2.4 GHz"),
        (5_180_000, 36, "5 GHz"),
        (5_500_000, 100, "5 GHz"),
        (5_825_000, 165, "5 GHz"),
        (5_935_000, 2, "6 GHz"),
        (5_955_000, 1, "6 GHz"),
        (7_115_000, 233, "6 GHz"),
        (0, None, "Unknown"),
        (915_000, None, "Unknown"),
        (2_413_000, None, "2.4 GHz"),
    ],
)
def test_frequency_to_channel(frequency, channel, band) -> None:
    assert frequency_to_channel(frequency) == (channel, band)


def test_parse_bss_entry_normalizes_all_fields() -> None:
    entry = WLAN_BSS_ENTRY()
    ssid = "Lab 🛜".encode()
    entry.dot11Ssid.uSSIDLength = len(ssid)
    entry.dot11Ssid.ucSSID[: len(ssid)] = ssid
    entry.dot11Bssid[:] = bytes.fromhex("aabbccddeeff")
    entry.lRssi = -57
    entry.ulChCenterFrequency = 5_955_000

    assert parse_bss_entry(entry) == {
        "ssid": "Lab 🛜",
        "bssid": "AA:BB:CC:DD:EE:FF",
        "band": "6 GHz",
        "rssi_dbm": -57,
        "channel": 1,
    }


def test_parse_bss_entry_handles_hidden_and_malformed_ssid() -> None:
    hidden = WLAN_BSS_ENTRY()
    assert parse_bss_entry(hidden)["ssid"] == "<hidden>"

    malformed = WLAN_BSS_ENTRY()
    malformed.dot11Ssid.uSSIDLength = 1
    malformed.dot11Ssid.ucSSID[0] = 0xFF
    assert "�" in parse_bss_entry(malformed)["ssid"]

    malformed.dot11Ssid.uSSIDLength = 99
    with pytest.raises(ValueError, match="SSID length"):
        parse_bss_entry(malformed)


def test_parse_bss_entry_rejects_impossible_rssi() -> None:
    entry = WLAN_BSS_ENTRY()
    entry.lRssi = 25
    with pytest.raises(ValueError, match="RSSI"):
        parse_bss_entry(entry)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (windows_wifi.ERROR_ACCESS_DENIED, "desktop apps access your location"),
        (windows_wifi.ERROR_SERVICE_NOT_ACTIVE, "WLAN AutoConfig"),
        (windows_wifi.ERROR_NDIS_DOT11_POWER_STATE_INVALID, "radio is turned off"),
    ],
)
def test_actionable_windows_errors(code, message) -> None:
    assert message in windows_wifi._error_message(code, "scan")


def test_windows_scanner_rejects_other_platforms(monkeypatch) -> None:
    monkeypatch.setattr(windows_wifi.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="only on Windows"):
        windows_wifi.scan_wifi()


def test_windows_scanner_reads_and_releases_native_allocations() -> None:
    api = FakeWlanApi()
    waits = []
    readings = windows_wifi.scan_wifi(api=api, settle=waits.append)
    assert readings == [
        {
            "ssid": "Test",
            "bssid": "00:11:22:33:44:55",
            "band": "5 GHz",
            "rssi_dbm": -48,
            "channel": 36,
        }
    ]
    assert waits == [windows_wifi.SCAN_SETTLE_SECONDS]
    assert set(api.freed) == {ctypes.addressof(api.interfaces), ctypes.addressof(api.bss)}
    assert api.closed


def test_windows_scanner_rejects_empty_scan_and_releases_allocations() -> None:
    api = FakeWlanApi()
    api.bss.dwNumberOfItems = 0
    api.bss.dwTotalSize = WLAN_BSS_LIST.wlanBssEntries.offset
    with pytest.raises(RuntimeError, match="no usable nearby"):
        windows_wifi.scan_wifi(api=api, settle=lambda _: None)
    assert set(api.freed) == {ctypes.addressof(api.interfaces), ctypes.addressof(api.bss)}
    assert api.closed


def test_windows_scanner_rejects_malformed_bss_buffer() -> None:
    api = FakeWlanApi()
    api.bss.dwTotalSize = WLAN_BSS_LIST.wlanBssEntries.offset
    with pytest.raises(RuntimeError, match="malformed Wi-Fi entry buffer"):
        windows_wifi.scan_wifi(api=api, settle=lambda _: None)
    assert api.closed


def test_windows_scanner_rejects_unreasonable_interface_count() -> None:
    api = FakeWlanApi()
    api.interfaces.dwNumberOfItems = windows_wifi.MAX_WLAN_INTERFACES + 1
    with pytest.raises(RuntimeError, match="invalid Wi-Fi adapter count"):
        windows_wifi.scan_wifi(api=api, settle=lambda _: None)
    assert api.closed
