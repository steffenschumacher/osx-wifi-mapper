from __future__ import annotations

import io

from PIL import Image

from native_wifi_mapper import SAMPLE_MARKER_DIAMETER, HeatmapWorker, ScanWorker, SurveyWindow
from survey_core import SurveyDocument, measurement_frame


def document() -> SurveyDocument:
    output = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, "PNG")
    return SurveyDocument(output.getvalue(), "office.png")


def test_native_window_constructs_and_closes(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "WiFi Site Survey — Native"
    window.close()
    assert not window.isVisible()


def test_map_preserves_aspect_and_calibrates(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.rebuild_scene()
    assert window.scene.sceneRect().width() == 100
    assert window.scene.sceneRect().height() == 50
    background = min(window.scene.items(), key=lambda item: item.zValue())
    assert background.pixmap().width() == 200
    assert background.scale() == 0.5

    window.map_clicked(10, 10)
    window.map_clicked(30, 10)
    window.distance_spin.setValue(10)
    window.apply_calibration()
    assert window.document.meters_per_unit == 0.5


def test_numbered_marker_is_visible_and_selectable(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.document.meters_per_unit = 1.0
    window.document.add_measurement(
        10,
        10,
        [{"ssid": "Home", "bssid": "AA", "band": "5 GHz", "rssi_dbm": -50, "channel": 44}],
    )
    window.rebuild_scene()
    markers = [item for item in window.scene.items() if item.data(0) == 1]
    assert len(markers) == 1
    assert markers[0].flags() & markers[0].GraphicsItemFlag.ItemIsSelectable
    assert "Home / AA / 5 GHz" in markers[0].toolTip()
    assert markers[0].rect().width() == SAMPLE_MARKER_DIAMETER
    assert not markers[0].number.isVisible()
    markers[0].number.setVisible(True)
    assert markers[0].number.isVisible()


def test_scan_worker_reports_success(monkeypatch, qtbot) -> None:
    expected = [{"ssid": "Home"}]
    monkeypatch.setattr("native_wifi_mapper.scan_wifi", lambda: expected)
    worker = ScanWorker()
    with qtbot.waitSignal(worker.signals.succeeded, timeout=1000) as signal:
        worker.run()
    assert signal.args == [expected]


def test_heatmap_worker_reports_surface(qtbot) -> None:
    survey = document()
    survey.meters_per_unit = 1.0
    reading = {
        "ssid": "Home",
        "bssid": "AA",
        "band": "5 GHz",
        "rssi_dbm": -55,
        "channel": 44,
    }
    for x, y in ((0, 0), (20, 0), (0, 20), (20, 20), (40, 20)):
        survey.add_measurement(x, y, [reading])
    worker = HeatmapWorker(
        7,
        measurement_frame(survey.measurements),
        [("Home", "AA", "5 GHz")],
        survey.y_max,
    )
    with qtbot.waitSignal(worker.signals.finished, timeout=1000) as signal:
        worker.run()
    assert signal.args[0] == 7
    assert signal.args[1] is not None


def test_filters_create_heatmap_and_point_deletion(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.document.meters_per_unit = 1.0
    reading = {
        "ssid": "Home",
        "bssid": "AA",
        "band": "5 GHz",
        "rssi_dbm": -55,
        "channel": 44,
    }
    for x, y in ((0, 0), (20, 0), (0, 20), (20, 20), (40, 20)):
        window.document.add_measurement(x, y, [reading])
    window.rebuild_scene()
    window.refresh_filters()

    assert window.ssid_list.count() == 1
    assert window.bssid_list.count() == 1
    assert window.band_list.count() == 1
    qtbot.waitUntil(
        lambda: any(item.data(1) == "heatmap" for item in window.scene.items()), timeout=2000
    )
    assert any(item.data(1) == "heatmap" for item in window.scene.items())

    marker = next(item for item in window.scene.items() if item.data(0) == 1)
    marker.setSelected(True)
    window.delete_selected_point()
    assert all(point["point_id"] != 1 for point in window.document.points)


def test_scan_failure_reenables_ui(monkeypatch, qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.map_view.setEnabled(False)
    monkeypatch.setattr("native_wifi_mapper.QMessageBox.warning", lambda *args: None)
    window.scan_failed("failure")
    assert window.map_view.isEnabled()
    assert not window.scan_banner.isVisible()


def test_scan_banner_blocks_then_announces_next_location(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.show()
    window.document = document()
    window.document.meters_per_unit = 1.0
    window.pending_scan = (10, 10)
    window.set_controls_enabled(False)
    window.show_scan_banner("Scanning")
    assert window.scan_banner.isVisible()
    assert not window.map_view.isEnabled()

    window.scan_succeeded([])
    assert window.map_view.isEnabled()
    assert window.scan_banner.isVisible()
    assert "free to walk" in window.scan_banner.text()
