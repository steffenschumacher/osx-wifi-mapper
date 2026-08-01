from __future__ import annotations

import io

from PIL import Image

from native_wifi_mapper import ScanWorker, SurveyWindow
from survey_core import SurveyDocument


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


def test_scan_worker_reports_success(monkeypatch, qtbot) -> None:
    expected = [{"ssid": "Home"}]
    monkeypatch.setattr("native_wifi_mapper.scan_wifi", lambda: expected)
    worker = ScanWorker()
    with qtbot.waitSignal(worker.signals.succeeded, timeout=1000) as signal:
        worker.run()
    assert signal.args == [expected]
