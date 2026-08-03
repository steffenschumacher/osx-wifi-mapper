from __future__ import annotations

import copy
import io

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsLineItem,
    QGraphicsScene,
    QPushButton,
)

from native_wifi_mapper import (
    PAN_THRESHOLD_PIXELS,
    SAMPLE_MARKER_DIAMETER,
    CalibrationDialog,
    HeatmapWorker,
    MapView,
    ScanWorker,
    StartupDialog,
    SurveyWindow,
)
from survey_core import SurveyDocument, measurement_frame


def document() -> SurveyDocument:
    output = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, "PNG")
    return SurveyDocument(output.getvalue(), "office.png")


def test_native_window_constructs_and_closes(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "WiFi Site Survey"
    window.close()
    assert not window.isVisible()


@pytest.mark.parametrize(
    ("choice", "method"), (("survey", "open_survey"), ("floorplan", "open_image"))
)
def test_startup_dialog_routes_both_choices(monkeypatch, qtbot, choice, method) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    called = []

    class AcceptedStartup:
        def __init__(self, parent) -> None:
            self.choice = choice

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr("native_wifi_mapper.StartupDialog", AcceptedStartup)
    monkeypatch.setattr(window, method, lambda: called.append(method))
    window.show_startup_dialog()
    assert called == [method]


def test_startup_dialog_exposes_survey_and_floorplan_choices(qtbot) -> None:
    dialog = StartupDialog()
    qtbot.addWidget(dialog)
    labels = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "Open Existing Survey…" in labels
    assert "Choose Floor Plan…" in labels
    dialog.select("survey")
    assert dialog.choice == "survey"
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_view_menu_zoom_reset_and_crosshair_cursor(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.document.calibration_points = [(0, 0), (10, 0)]
    window.document.meters_per_unit = 0.5
    window.rebuild_scene()
    baseline = window.map_view.transform().m11()
    window.map_view.zoom_in()
    assert window.map_view.transform().m11() > baseline
    window.map_view.reset_zoom()
    assert window.map_view.transform().m11() == pytest.approx(baseline)
    assert window.map_view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
    menu_names = {action.text() for action in window.menuBar().actions()}
    assert "View" in menu_names


def test_drag_pans_without_emitting_sample_and_click_does_emit(qtbot) -> None:
    view = MapView()
    qtbot.addWidget(view)
    scene = QGraphicsScene(view)
    scene.setSceneRect(0, 0, 100, 50)
    view.setScene(scene)
    view.set_y_max(50)
    view.resize(500, 300)
    view.show()
    view.fit_map()
    view.zoom_in()
    view.zoom_in()
    samples = []
    view.map_clicked.connect(lambda x, y: samples.append((x, y)))
    start = QPoint(250, 150)

    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start + QPoint(PAN_THRESHOLD_PIXELS + 20, 0))
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=start + QPoint(PAN_THRESHOLD_PIXELS + 20, 0),
    )
    assert samples == []
    assert view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor

    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert len(samples) == 1


def test_map_preserves_aspect(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.document.calibration_points = [(10, 10), (30, 10)]
    window.document.meters_per_unit = 0.5
    window.rebuild_scene()
    assert window.scene.sceneRect().width() == 100
    assert window.scene.sceneRect().height() == 50
    background = min(window.scene.items(), key=lambda item: item.zValue())
    assert background.pixmap().width() == 200
    assert background.scale() == 0.5
    ruler_lines = [item for item in window.scene.items() if isinstance(item, QGraphicsLineItem)]
    assert len(ruler_lines) == 3
    assert all(item.pen().color() == QColor("black") for item in ruler_lines)
    assert any(item.data(2) == "scale-ruler" for item in window.scene.items())


def test_calibration_dialog_draws_points_and_line_and_accepts(qtbot) -> None:
    dialog = CalibrationDialog(document())
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    background = min(dialog.scene.items(), key=lambda item: item.zValue())

    dialog.map_clicked(10, 10)
    dialog.map_clicked(30, 10)
    dialog.distance_spin.setValue(10)
    assert ok.isEnabled()
    assert sum(isinstance(item, QGraphicsLineItem) for item in dialog.scene.items()) == 1
    assert background in dialog.scene.items()
    assert dialog.meters_per_unit == 0.5
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


class FakeCalibrationDialog:
    def __init__(self, accepted: bool) -> None:
        self.result = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        self.calibration_points = [(10.0, 10.0), (30.0, 10.0)]
        self.meters_per_unit = 0.5

    def exec(self) -> QDialog.DialogCode:
        return self.result


def test_open_image_forces_calibration_and_cancel_unloads(monkeypatch, qtbot, tmp_path) -> None:
    path = tmp_path / "floor.png"
    path.write_bytes(document().image_bytes)
    window = SurveyWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "native_wifi_mapper.QFileDialog.getOpenFileName", lambda *args: (str(path), "")
    )
    monkeypatch.setattr(
        window, "create_calibration_dialog", lambda candidate: FakeCalibrationDialog(False)
    )

    window.open_image()
    assert window.document is None
    assert not window.map_view.isEnabled()
    assert "Stage 1" in window.calibration_status.text()


def test_open_image_acceptance_enters_sampling_stage(monkeypatch, qtbot, tmp_path) -> None:
    path = tmp_path / "floor.png"
    path.write_bytes(document().image_bytes)
    window = SurveyWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "native_wifi_mapper.QFileDialog.getOpenFileName", lambda *args: (str(path), "")
    )
    monkeypatch.setattr(
        window, "create_calibration_dialog", lambda candidate: FakeCalibrationDialog(True)
    )

    window.open_image()
    assert window.document is not None
    assert window.document.meters_per_unit == 0.5
    assert window.map_view.isEnabled()
    assert "Calibrated" in window.calibration_status.text()


def test_cancelled_recalibration_preserves_active_survey(monkeypatch, qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    survey = document()
    survey.calibration_points = [(0.0, 0.0), (10.0, 0.0)]
    survey.meters_per_unit = 0.25
    survey.add_measurement(
        5,
        5,
        [{"ssid": "Home", "bssid": "AA", "band": "5 GHz", "rssi_dbm": -50, "channel": 44}],
    )
    window.activate_document(survey)
    before = copy.deepcopy(
        (survey.calibration_points, survey.meters_per_unit, survey.points, survey.measurements)
    )
    monkeypatch.setattr(
        window, "create_calibration_dialog", lambda candidate: FakeCalibrationDialog(False)
    )

    window.recalibrate()
    assert window.document is survey
    assert (
        survey.calibration_points,
        survey.meters_per_unit,
        survey.points,
        survey.measurements,
    ) == before


def test_successful_recalibration_updates_scale_without_losing_samples(monkeypatch, qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    survey = document()
    survey.calibration_points = [(0.0, 0.0), (10.0, 0.0)]
    survey.meters_per_unit = 0.25
    survey.add_measurement(
        5,
        5,
        [
            {
                "ssid": "Home",
                "bssid": "AA",
                "band": "5 GHz",
                "rssi_dbm": -50,
                "channel": 44,
            }
        ],
    )
    window.activate_document(survey)
    points_before = copy.deepcopy(survey.points)
    measurements_before = copy.deepcopy(survey.measurements)
    monkeypatch.setattr(
        window, "create_calibration_dialog", lambda candidate: FakeCalibrationDialog(True)
    )

    window.recalibrate()
    assert survey.calibration_points == [(10.0, 10.0), (30.0, 10.0)]
    assert survey.meters_per_unit == 0.5
    assert survey.points == points_before
    assert survey.measurements == measurements_before


def test_calibrated_survey_loads_without_dialog(monkeypatch, qtbot, tmp_path) -> None:
    survey = document()
    survey.calibration_points = [(0.0, 0.0), (10.0, 0.0)]
    survey.meters_per_unit = 0.5
    path = tmp_path / "ready.wifisurvey"
    path.write_bytes(survey.to_bytes())
    window = SurveyWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "native_wifi_mapper.QFileDialog.getOpenFileName", lambda *args: (str(path), "")
    )
    monkeypatch.setattr(
        window,
        "create_calibration_dialog",
        lambda candidate: (_ for _ in ()).throw(AssertionError("dialog should not open")),
    )

    window.open_survey()
    assert window.document is not None
    assert window.map_view.isEnabled()


def test_uncalibrated_survey_requires_dialog_and_cancel_unloads(
    monkeypatch, qtbot, tmp_path
) -> None:
    path = tmp_path / "uncalibrated.wifisurvey"
    path.write_bytes(document().to_bytes())
    window = SurveyWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "native_wifi_mapper.QFileDialog.getOpenFileName", lambda *args: (str(path), "")
    )
    monkeypatch.setattr(
        window, "create_calibration_dialog", lambda candidate: FakeCalibrationDialog(False)
    )

    window.open_survey()
    assert window.document is None
    assert not window.map_view.isEnabled()


def test_sampling_is_blocked_before_calibration(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    window.document = document()
    window.map_clicked(10, 10)
    assert window.pending_scan is None
    assert "Complete stage 1" in window.statusBar().currentMessage()


def test_coincident_calibration_endpoints_do_not_unlock_sampling(qtbot) -> None:
    window = SurveyWindow()
    qtbot.addWidget(window)
    survey = document()
    survey.calibration_points = [(10.0, 10.0), (10.0, 10.0)]
    survey.meters_per_unit = 1.0
    window.document = survey
    window.update_stage_ui()
    assert not window.map_view.isEnabled()


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
    assert markers[0].brush().color() == QColor("black")
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
