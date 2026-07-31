from __future__ import annotations

import sys
import types

import pandas as pd
import pytest
from PIL import Image

import wifi_site_survey as app


def test_rssi_color_thresholds() -> None:
    assert app.rssi_color(-59) == "#22c55e"
    assert app.rssi_color(-60) == "#facc15"
    assert app.rssi_color(-75) == "#facc15"
    assert app.rssi_color(-76) == "#ef4444"


def test_selected_point_summary_supports_strongest_and_average() -> None:
    frame = pd.DataFrame(
        [
            {"point_id": 1, "x": 10.0, "y": 20.0, "ssid": "Home", "bssid": "A", "rssi_dbm": -50},
            {"point_id": 1, "x": 10.0, "y": 20.0, "ssid": "Home", "bssid": "B", "rssi_dbm": -70},
            {"point_id": 2, "x": 30.0, "y": 40.0, "ssid": "Guest", "bssid": "C", "rssi_dbm": -80},
        ]
    )

    strongest = app.selected_point_summary(frame, ["Home"], ["A", "B"], "Strongest")
    average = app.selected_point_summary(frame, ["Home"], ["A", "B"], "Average")

    assert strongest.iloc[0]["rssi_dbm"] == -50
    assert average.iloc[0]["rssi_dbm"] == -60
    assert strongest.iloc[0]["access_points"] == 2


def test_empty_filters_produce_empty_summary() -> None:
    frame = pd.DataFrame(columns=app.MEASUREMENT_COLUMNS)
    assert app.selected_point_summary(frame, [], [], "Strongest").empty


def test_build_map_contains_click_layer_and_colored_points() -> None:
    image = Image.new("RGB", (20, 10), "white")
    points = pd.DataFrame(
        [{"point_id": 1, "x": 25.0, "y": 75.0, "rssi_dbm": -55, "access_points": 2}]
    )

    figure = app.build_map(image, points)

    assert len(figure.layout.images) == 1
    assert figure.layout.xaxis.range == (0, 100)
    assert figure.layout.yaxis.range == (0, 100)
    assert figure.data[0].type == "heatmap"
    assert figure.data[1].marker.color == ("#22c55e",)


def test_add_measurement_point_records_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    state = types.SimpleNamespace(
        points=[], measurements=[], next_point_id=7, map_revision=0, floorplan_hash=None
    )
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(
        app,
        "scan_wifi",
        lambda: [{"ssid": "Home", "bssid": "A", "rssi_dbm": -42, "channel": 6}],
    )

    point_id, count = app.add_measurement_point(12.345, 67.899)

    assert (point_id, count) == (7, 1)
    assert state.points[0]["x"] == 12.35
    assert state.points[0]["y"] == 67.9
    assert state.measurements[0]["ssid"] == "Home"
    assert state.next_point_id == 8


def test_scan_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="only on macOS"):
        app.scan_wifi()


def test_scan_extracts_corewlan_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class Channel:
        def channelNumber(self) -> int:
            return 44

    class Network:
        def ssid(self) -> str:
            return "Office"

        def bssid(self) -> str:
            return "aa:bb:cc:dd:ee:ff"

        def rssiValue(self) -> int:
            return -63

        def wlanChannel(self) -> Channel:
            return Channel()

    class Interface:
        def scanForNetworksWithName_error_(self, name: None, error: None):
            assert name is None and error is None
            return [Network()], None

    class Client:
        @staticmethod
        def sharedWiFiClient() -> Client:
            return Client()

        def interface(self) -> Interface:
            return Interface()

    def load_bundle(*args, **kwargs) -> None:
        app.CWWiFiClient = Client

    monkeypatch.setattr(app.platform, "system", lambda: "Darwin")
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(loadBundle=load_bundle))

    assert app.scan_wifi() == [
        {"ssid": "Office", "bssid": "AA:BB:CC:DD:EE:FF", "rssi_dbm": -63, "channel": 44}
    ]
