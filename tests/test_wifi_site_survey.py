from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd
import pytest
from PIL import Image

import wifi_site_survey as app


def sample_rows(
    count: int,
    *,
    ssid: str = "Home",
    bssid: str = "AA",
    band: str = "5 GHz",
    rssi: int = -60,
    collinear: bool = False,
) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        x = float(index * 5)
        y = float(index * 5 if collinear else (index % 3) * 10)
        rows.append(
            {
                "point_id": index + 1,
                "x": x,
                "y": y,
                "measured_at_utc": "2026-01-01T00:00:00+00:00",
                "ssid": ssid,
                "bssid": bssid,
                "band": band,
                "rssi_dbm": rssi + index,
                "channel": 44,
            }
        )
    return rows


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1, "2.4 GHz"), (2, "5 GHz"), (3, "6 GHz"), (0, "Unknown"), (99, "Unknown")],
)
def test_normalize_band(raw: int, expected: str) -> None:
    assert app.normalize_band(raw) == expected


def test_rssi_color_thresholds_and_fixed_scale() -> None:
    assert app.rssi_color(-59) == "#22c55e"
    assert app.rssi_color(-60) == "#facc15"
    assert app.rssi_color(-75) == "#facc15"
    assert app.rssi_color(-76) == "#ef4444"
    assert app.RSSI_MIN == -90
    assert app.RSSI_MAX == -40


def test_measurement_frame_preserves_band_and_channel_and_upgrades_old_rows() -> None:
    current = app.measurement_frame(sample_rows(1))
    assert list(current.columns) == app.MEASUREMENT_COLUMNS
    assert current.iloc[0]["band"] == "5 GHz"
    assert current.iloc[0]["channel"] == 44

    old_row = sample_rows(1)[0]
    old_row.pop("band")
    assert app.measurement_frame([old_row]).iloc[0]["band"] == "Unknown"


def test_eligibility_requires_five_one_metre_spaced_coordinates() -> None:
    four = app.triple_eligibility(app.measurement_frame(sample_rows(4)), 1.0).iloc[0]
    five = app.triple_eligibility(app.measurement_frame(sample_rows(5)), 1.0).iloc[0]

    assert not bool(four["eligible"])
    assert four["reason"] == "4/5 points"
    assert bool(five["eligible"])
    assert five["sample_count"] == 5


def test_eligibility_requires_calibration_and_one_metre_spacing() -> None:
    measurements = app.measurement_frame(sample_rows(5))
    uncalibrated = app.triple_eligibility(measurements).iloc[0]
    too_close = app.triple_eligibility(measurements, 0.05).iloc[0]

    assert uncalibrated["reason"] == "distance calibration required"
    assert not bool(uncalibrated["eligible"])
    assert too_close["sample_count"] < 5
    assert not bool(too_close["eligible"])


def test_calibration_and_minimum_point_spacing() -> None:
    assert app.calibration_scale((0.0, 0.0), (3.0, 4.0), 10.0) == 2.0
    points = pd.DataFrame([{"x": 10.0, "y": 10.0}])

    assert not app.point_has_minimum_spacing(10.5, 10.0, points, 1.0)
    assert app.point_has_minimum_spacing(11.0, 10.0, points, 1.0)

    with pytest.raises(ValueError, match="different"):
        app.calibration_scale((1.0, 1.0), (1.0, 1.0), 2.0)


def test_click_coordinates_support_values_and_heatmap_indices() -> None:
    x_axis = np.array([0.0, 50.0, 100.0])
    y_axis = np.array([0.0, 25.0, 50.0])

    assert app.click_coordinates({"x": 12.5, "y": 7.5}, x_axis, y_axis) == (12.5, 7.5)
    assert app.click_coordinates({"pointNumber": [1, 2]}, x_axis, y_axis) == (100.0, 25.0)


def test_duplicate_coordinates_do_not_inflate_eligibility() -> None:
    rows = sample_rows(4)
    duplicate = dict(rows[0], point_id=99, rssi_dbm=-30)
    result = app.triple_eligibility(app.measurement_frame([*rows, duplicate]), 1.0).iloc[0]

    assert result["sample_count"] == 4
    assert not bool(result["eligible"])


def test_collinear_samples_are_ineligible() -> None:
    result = app.triple_eligibility(
        app.measurement_frame(sample_rows(5, collinear=True)), 1.0
    ).iloc[0]

    assert not bool(result["eligible"])
    assert result["reason"] == "insufficient spatial spread"


def test_effectively_collinear_samples_are_ineligible() -> None:
    rows = sample_rows(5)
    for index, row in enumerate(rows):
        row["y"] = float(index * 0.001)
    result = app.triple_eligibility(app.measurement_frame(rows), 1.0).iloc[0]

    assert not bool(result["eligible"])
    assert result["reason"] == "insufficient spatial spread"


def test_filtering_returns_only_matching_eligible_triples() -> None:
    measurements = app.measurement_frame(
        [
            *sample_rows(5, ssid="Home", bssid="AA", band="5 GHz"),
            *sample_rows(5, ssid="Home", bssid="BB", band="2.4 GHz"),
            *sample_rows(4, ssid="Guest", bssid="CC", band="6 GHz"),
        ]
    )
    eligibility = app.triple_eligibility(measurements, 1.0)

    assert app.select_eligible_triples(eligibility, ["Home"], ["AA", "CC"], ["5 GHz", "6 GHz"]) == [
        ("Home", "AA", "5 GHz")
    ]
    assert app.select_eligible_triples(eligibility, [], ["AA"], ["5 GHz"]) == [
        ("Home", "AA", "5 GHz")
    ]
    assert set(app.select_eligible_triples(eligibility, [], [], [])) == {
        ("Home", "AA", "5 GHz"),
        ("Home", "BB", "2.4 GHz"),
    }


def test_interpolation_preserves_samples_and_masks_outside_hull() -> None:
    coordinates = np.array([[0.0, 0.0], [100.0, 0.0], [0.0, 100.0]])
    values = np.array([-50.0, -60.0, -70.0])
    axis = np.array([0.0, 50.0, 100.0])

    surface = app.interpolate_rssi(coordinates, values, axis)

    assert surface[0, 0] == -50.0
    assert surface[0, 2] == -60.0
    assert surface[2, 0] == -70.0
    assert np.isfinite(surface[1, 1])
    assert np.isnan(surface[2, 2])


def test_combine_surfaces_uses_max_and_preserves_unknown_cells() -> None:
    first = np.array([[-60.0, np.nan], [-80.0, np.nan]])
    second = np.array([[-70.0, -50.0], [np.nan, np.nan]])

    combined = app.combine_surfaces([first, second])

    assert combined is not None
    np.testing.assert_allclose(combined[0], [-60.0, -50.0])
    assert combined[1, 0] == -80.0
    assert np.isnan(combined[1, 1])
    assert app.combine_surfaces([]) is None


def test_heatmap_interpolates_triples_independently_then_uses_strongest() -> None:
    rows = [
        *sample_rows(5, bssid="AA", rssi=-70),
        *sample_rows(5, bssid="BB", rssi=-50),
    ]
    x_axis, y_axis, surface = app.heatmap_surface(
        app.measurement_frame(rows),
        [("Home", "AA", "5 GHz"), ("Home", "BB", "5 GHz")],
        resolution=21,
    )

    assert len(x_axis) == 21
    assert len(y_axis) == 21
    assert surface is not None
    assert surface[0, 0] == -50.0


def test_hover_and_marker_frame_include_all_readings() -> None:
    rows = sample_rows(1)
    rows.append(dict(rows[0], ssid="Guest", bssid="BB", band="2.4 GHz", channel=None, rssi_dbm=-80))
    measurements = app.measurement_frame(rows)
    points = pd.DataFrame([{"point_id": 1, "x": 0.0, "y": 0.0}])

    markers = app.marker_frame(points, measurements)

    assert "Home / AA / 5 GHz / channel 44" in markers.iloc[0]["hover"]
    assert "Guest / BB / 2.4 GHz / channel Unknown: -80 dBm" in markers.iloc[0]["hover"]


def test_hover_escapes_network_names() -> None:
    rows = sample_rows(1, ssid="<script>", bssid="A&B")
    hover = app.format_hover_readings(app.measurement_frame(rows))

    assert "&lt;script&gt; / A&amp;B" in hover
    assert "<script>" not in hover


def test_build_map_layers_click_surface_heatmap_and_markers() -> None:
    image = Image.new("RGB", (20, 10), "white")
    markers = pd.DataFrame([{"point_id": 1, "x": 25.0, "y": 75.0, "hover": "Reading"}])
    axis = np.array([0.0, 100.0])
    surface = np.array([[-80.0, -70.0], [-60.0, np.nan]])

    figure = app.build_map(image, markers, axis, axis / 2, surface, 0.4)

    assert len(figure.layout.images) == 1
    assert [trace.type for trace in figure.data] == ["heatmap", "heatmap", "scatter"]
    assert figure.data[1].zmin == app.RSSI_MIN
    assert figure.data[1].zmax == app.RSSI_MAX
    assert figure.data[1].opacity == 0.4
    assert figure.data[2].marker.symbol == "diamond"
    assert figure.layout.images[0].sizey == 50
    assert figure.layout.yaxis.range == (0, 50)
    serialized = figure.to_plotly_json()
    assert isinstance(serialized["data"][0]["x"], list)
    assert isinstance(serialized["data"][1]["x"], list)
    assert isinstance(serialized["data"][1]["z"], list)


def test_add_and_delete_measurement_recalculates_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = sample_rows(4)
    points = [
        {"point_id": row["point_id"], "x": row["x"], "y": row["y"], "access_points": 1}
        for row in rows
    ]
    state = types.SimpleNamespace(
        points=points,
        measurements=rows,
        next_point_id=5,
        map_revision=0,
        floorplan_hash=None,
    )
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(
        app,
        "scan_wifi",
        lambda: [
            {
                "ssid": "Home",
                "bssid": "AA",
                "band": "5 GHz",
                "rssi_dbm": -42,
                "channel": 44,
            }
        ],
    )

    point_id, count = app.add_measurement_point(50.0, 40.0)
    assert (point_id, count) == (5, 1)
    assert bool(
        app.triple_eligibility(app.measurement_frame(state.measurements), 1.0).iloc[0]["eligible"]
    )

    app.delete_measurement_point(5)
    after = app.triple_eligibility(app.measurement_frame(state.measurements), 1.0).iloc[0]
    assert after["sample_count"] == 4
    assert not bool(after["eligible"])
    assert state.map_revision == 1


def test_scan_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="only on macOS"):
        app.scan_wifi()


@pytest.mark.parametrize("status", [3, 4])
def test_authorized_location_status_allows_scans(status: int) -> None:
    assert app.location_permission_error(status) is None


@pytest.mark.parametrize("status", [None, 0, 1, 2])
def test_missing_location_permission_has_actionable_error(status: int | None) -> None:
    message = app.location_permission_error(status)

    assert message is not None
    assert "Location" in message or "location" in message


def test_request_location_authorization_retains_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = types.SimpleNamespace(requestWhenInUseAuthorization=lambda: None)
    requested = []
    manager.requestWhenInUseAuthorization = lambda: requested.append(True)
    monkeypatch.setattr(app, "location_authorization", lambda: (0, manager))
    monkeypatch.delattr(app.sys, "frozen", raising=False)

    status, returned_manager = app.request_location_authorization()

    assert status == 0
    assert returned_manager is manager
    assert requested == [True]


@pytest.mark.parametrize(
    ("raw_band", "expected"), [(1, "2.4 GHz"), (2, "5 GHz"), (3, "6 GHz"), (9, "Unknown")]
)
def test_scan_extracts_corewlan_fields(
    monkeypatch: pytest.MonkeyPatch, raw_band: int, expected: str
) -> None:
    class Channel:
        def channelNumber(self) -> int:
            return 44

        def channelBand(self) -> int:
            return raw_band

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
    monkeypatch.setattr(app, "location_authorization", lambda: (4, None))
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(loadBundle=load_bundle))

    assert app.scan_wifi() == [
        {
            "ssid": "Office",
            "bssid": "AA:BB:CC:DD:EE:FF",
            "band": expected,
            "rssi_dbm": -63,
            "channel": 44,
        }
    ]


def test_scan_rejects_fully_redacted_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class Channel:
        def channelNumber(self) -> int:
            return 44

        def channelBand(self) -> int:
            return 2

    class RedactedNetwork:
        def ssid(self):
            return None

        def bssid(self):
            return None

        def rssiValue(self) -> int:
            return -63

        def wlanChannel(self) -> Channel:
            return Channel()

    class Interface:
        def scanForNetworksWithName_error_(self, name: None, error: None):
            return [RedactedNetwork()], None

    class Client:
        @staticmethod
        def sharedWiFiClient() -> Client:
            return Client()

        def interface(self) -> Interface:
            return Interface()

    def load_bundle(*args, **kwargs) -> None:
        app.CWWiFiClient = Client

    monkeypatch.setattr(app.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(app, "location_authorization", lambda: (4, None))
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(loadBundle=load_bundle))

    with pytest.raises(RuntimeError, match="redacted every SSID and BSSID"):
        app.scan_wifi()
