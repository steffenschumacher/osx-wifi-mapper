"""Responsive browser-free PySide6 application for Wi-Fi site surveys."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from macos_wifi import (
    LOCATION_STATUS_NAMES,
    location_authorization,
    request_location_authorization,
    scan_wifi,
)
from survey_core import (
    RSSI_MAX,
    RSSI_MIN,
    SurveyDocument,
    heatmap_surface,
    measurement_frame,
    point_has_minimum_spacing,
    select_eligible_triples,
    triple_eligibility,
)


class MapView(QGraphicsView):
    map_clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._y_max = 100.0

    def set_y_max(self, value: float) -> None:
        self._y_max = value

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if 0 <= point.x() <= 100 and 0 <= point.y() <= self._y_max:
                self.map_clicked.emit(point.x(), self._y_max - point.y())
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def fit_map(self) -> None:
        self.fitInView(0, 0, 100, self._y_max, Qt.AspectRatioMode.KeepAspectRatio)


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class ScanWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.succeeded.emit(scan_wifi())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class SurveyWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WiFi Site Survey — Native")
        self.resize(1200, 800)
        self.document: SurveyDocument | None = None
        self.pending_scan: tuple[float, float] | None = None
        self.location_manager = None
        self.thread_pool = QThreadPool.globalInstance()
        self.scene = QGraphicsScene(self)
        self.map_view = MapView()
        self.map_view.setScene(self.scene)
        self.map_view.map_clicked.connect(self.map_clicked)
        self.setCentralWidget(self.map_view)
        self._build_controls()
        self._build_menu()
        self.statusBar().showMessage("Open a floor plan or saved survey to begin")
        self.refresh_location()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        for label, slot, shortcut in (
            ("Open Floor Plan…", self.open_image, "Ctrl+O"),
            ("Open Survey…", self.open_survey, "Ctrl+Shift+O"),
            ("Save Survey…", self.save_survey, "Ctrl+S"),
            ("Export CSV…", self.export_csv, "Ctrl+E"),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_controls(self) -> None:
        dock = QDockWidget("Survey Controls", self)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.location_label = QLabel()
        self.location_button = QPushButton("Request Location Access")
        self.location_button.clicked.connect(self.request_location)
        layout.addWidget(self.location_label)
        layout.addWidget(self.location_button)
        calibration = QGroupBox("Distance calibration")
        form = QFormLayout(calibration)
        self.calibration_label = QLabel("Open a floor plan")
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.01, 100000)
        self.distance_spin.setValue(1)
        self.distance_spin.setSuffix(" m")
        self.apply_calibration_button = QPushButton("Apply calibration")
        self.apply_calibration_button.clicked.connect(self.apply_calibration)
        self.recalibrate_button = QPushButton("Recalibrate")
        self.recalibrate_button.clicked.connect(self.recalibrate)
        form.addRow(self.calibration_label)
        form.addRow("Reference distance", self.distance_spin)
        form.addRow(self.apply_calibration_button)
        form.addRow(self.recalibrate_button)
        layout.addWidget(calibration)
        filters = QGroupBox("Heatmap filters (none selected = all)")
        filter_layout = QFormLayout(filters)
        self.ssid_list, self.bssid_list, self.band_list = (
            QListWidget(),
            QListWidget(),
            QListWidget(),
        )
        for widget in (self.ssid_list, self.bssid_list, self.band_list):
            widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            widget.itemSelectionChanged.connect(self.refresh_heatmap)
        filter_layout.addRow("SSID", self.ssid_list)
        filter_layout.addRow("BSSID", self.bssid_list)
        filter_layout.addRow("Band", self.band_list)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(10, 90)
        self.opacity.setValue(55)
        self.opacity.valueChanged.connect(self.refresh_heatmap)
        filter_layout.addRow("Opacity", self.opacity)
        layout.addWidget(filters)
        self.delete_button = QPushButton("Delete selected map point")
        self.delete_button.clicked.connect(self.delete_selected_point)
        layout.addWidget(self.delete_button)
        layout.addStretch()
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def refresh_location(self) -> None:
        status, manager = location_authorization()
        self.location_manager = manager
        self.location_label.setText(f"Location: {LOCATION_STATUS_NAMES.get(status, 'Unavailable')}")
        self.location_button.setEnabled(status == 0)

    def request_location(self) -> None:
        _, self.location_manager = request_location_authorization()
        self.statusBar().showMessage("Respond to the macOS prompt, then restart the app")

    def open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Floor Plan", "", "Images (*.png *.jpg *.jpeg)"
        )
        if path:
            self.document = SurveyDocument(Path(path).read_bytes(), Path(path).name)
            self.rebuild_scene()
            self.refresh_filters()

    def open_survey(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Survey", "", "WiFi surveys (*.wifisurvey)"
        )
        if not path:
            return
        try:
            self.document = SurveyDocument.from_bytes(Path(path).read_bytes())
            self.rebuild_scene()
            self.refresh_filters()
            self.statusBar().showMessage(f"Loaded {len(self.document.points)} points")
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid survey", str(exc))

    def save_survey(self) -> None:
        if not self.document:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Survey", "wifi_site_survey.wifisurvey", "WiFi surveys (*.wifisurvey)"
        )
        if path:
            Path(path).write_bytes(self.document.to_bytes())

    def export_csv(self) -> None:
        if not self.document:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "wifi_site_survey.csv", "CSV (*.csv)"
        )
        if path:
            measurement_frame(self.document.measurements).to_csv(
                path, index=False, quoting=csv.QUOTE_MINIMAL
            )

    def map_clicked(self, x: float, y: float) -> None:
        if not self.document:
            return
        if self.document.meters_per_unit is None:
            if len(self.document.calibration_points) >= 2:
                self.document.calibration_points.clear()
            self.document.calibration_points.append((x, y))
            self.rebuild_scene()
            return
        points = pd.DataFrame(self.document.points)
        if not point_has_minimum_spacing(x, y, points, self.document.meters_per_unit):
            self.statusBar().showMessage("Measurement points must be at least one metre apart")
            return
        self.pending_scan = (x, y)
        self.set_controls_enabled(False)
        self.statusBar().showMessage("Scanning Wi-Fi networks…")
        worker = ScanWorker()
        worker.signals.succeeded.connect(self.scan_succeeded)
        worker.signals.failed.connect(self.scan_failed)
        self.thread_pool.start(worker)

    def scan_succeeded(self, readings: object) -> None:
        if self.document and self.pending_scan:
            point_id = self.document.add_measurement(*self.pending_scan, readings)
            self.statusBar().showMessage(f"Captured point {point_id}: {len(readings)} APs")
        self.pending_scan = None
        self.set_controls_enabled(True)
        self.refresh_filters()
        self.rebuild_scene()

    def scan_failed(self, message: str) -> None:
        self.pending_scan = None
        self.set_controls_enabled(True)
        QMessageBox.warning(self, "Scan failed", message)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.map_view.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)

    def apply_calibration(self) -> None:
        if self.document and len(self.document.calibration_points) == 2:
            from survey_core import calibration_scale

            self.document.meters_per_unit = calibration_scale(
                *self.document.calibration_points, self.distance_spin.value()
            )
            self.rebuild_scene()
            self.refresh_filters()

    def recalibrate(self) -> None:
        if self.document:
            self.document.calibration_points.clear()
            self.document.meters_per_unit = None
            self.rebuild_scene()
            self.refresh_filters()

    def selected_values(self, widget: QListWidget) -> list[str]:
        return [item.text() for item in widget.selectedItems()]

    def refresh_filters(self) -> None:
        selections = [
            self.selected_values(widget)
            for widget in (self.ssid_list, self.bssid_list, self.band_list)
        ]
        frame = measurement_frame(self.document.measurements if self.document else [])
        eligibility = triple_eligibility(
            frame, self.document.meters_per_unit if self.document else None
        )
        eligible = eligibility[eligibility.eligible] if not eligibility.empty else eligibility
        for widget, column, selected in zip(
            (self.ssid_list, self.bssid_list, self.band_list),
            ("ssid", "bssid", "band"),
            selections,
            strict=True,
        ):
            widget.blockSignals(True)
            widget.clear()
            for value in sorted(eligible[column].unique() if not eligible.empty else []):
                item = QListWidgetItem(str(value))
                widget.addItem(item)
                item.setSelected(str(value) in selected)
            widget.blockSignals(False)
        self.refresh_heatmap()

    def rebuild_scene(self) -> None:
        self.scene.clear()
        if not self.document:
            return
        image = self.document.image
        rgba = image.convert("RGBA")
        data = rgba.tobytes("raw", "RGBA")
        qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(qimage).scaledToWidth(
            100, Qt.TransformationMode.SmoothTransformation
        )
        background = self.scene.addPixmap(pixmap)
        background.setZValue(0)
        self.scene.setSceneRect(0, 0, 100, self.document.y_max)
        self.map_view.set_y_max(self.document.y_max)
        self.draw_calibration()
        self.draw_markers()
        self.refresh_heatmap()
        self.map_view.fit_map()

    def draw_calibration(self) -> None:
        if not self.document:
            return
        if not self.document.calibration_points:
            self.calibration_label.setText("Click endpoint 1")
            return
        points = [QPointF(x, self.document.y_max - y) for x, y in self.document.calibration_points]
        if len(points) == 2:
            line = self.scene.addLine(
                points[0].x(),
                points[0].y(),
                points[1].x(),
                points[1].y(),
                QPen(QColor("#7c3aed"), 0.8),
            )
            line.setZValue(3)
        for point in points:
            marker = self.scene.addEllipse(
                point.x() - 1, point.y() - 1, 2, 2, QPen(Qt.PenStyle.NoPen), QColor("#7c3aed")
            )
            marker.setZValue(4)
        count = len(points)
        self.calibration_label.setText(
            "Calibrated"
            if self.document.meters_per_unit
            else f"Click endpoint {count + 1}"
            if count < 2
            else "Enter distance and apply"
        )

    def draw_markers(self) -> None:
        if not self.document:
            return
        grouped = {
            key: group
            for key, group in measurement_frame(self.document.measurements).groupby("point_id")
        }
        for point in self.document.points:
            x, y, point_id = (
                float(point["x"]),
                self.document.y_max - float(point["y"]),
                int(point["point_id"]),
            )
            marker = QGraphicsEllipseItem(x - 1.8, y - 1.8, 3.6, 3.6)
            marker.setBrush(QColor("#2563eb"))
            marker.setPen(QPen(QColor("white"), 0.5))
            marker.setZValue(5)
            marker.setFlag(marker.GraphicsItemFlag.ItemIsSelectable)
            readings = grouped.get(point_id, pd.DataFrame())
            marker.setToolTip(
                "\n".join(
                    f"{r.ssid} / {r.bssid} / {r.band} / ch {r.channel}: {r.rssi_dbm} dBm"
                    for r in readings.itertuples()
                )
            )
            marker.setData(0, point_id)
            self.scene.addItem(marker)
            label = QGraphicsSimpleTextItem(str(point_id))
            label.setBrush(QColor("white"))
            label.setScale(0.12)
            label.setPos(x - 0.7, y - 0.9)
            label.setZValue(6)
            self.scene.addItem(label)

    def delete_selected_point(self) -> None:
        if not self.document:
            return
        ids = [item.data(0) for item in self.scene.selectedItems() if item.data(0)]
        if ids:
            self.document.delete_point(int(ids[0]))
            self.refresh_filters()
            self.rebuild_scene()

    def refresh_heatmap(self) -> None:
        if not self.document:
            return
        for item in self.scene.items():
            if item.data(1) == "heatmap":
                self.scene.removeItem(item)
        frame = measurement_frame(self.document.measurements)
        eligibility = triple_eligibility(frame, self.document.meters_per_unit)
        triples = select_eligible_triples(
            eligibility,
            self.selected_values(self.ssid_list),
            self.selected_values(self.bssid_list),
            self.selected_values(self.band_list),
        )
        _, _, surface = heatmap_surface(frame, triples, 151, self.document.y_max)
        if surface is None:
            return
        normalized = np.clip((surface - RSSI_MIN) / (RSSI_MAX - RSSI_MIN), 0, 1)
        rgba = np.zeros((*surface.shape, 4), dtype=np.uint8)
        rgba[..., 0] = np.where(normalized < 0.5, 239, np.where(normalized < 0.7, 250, 34))
        rgba[..., 1] = np.where(normalized < 0.5, 68, np.where(normalized < 0.7, 204, 197))
        rgba[..., 2] = np.where(normalized < 0.5, 68, np.where(normalized < 0.7, 21, 94))
        rgba[..., 3] = np.where(np.isfinite(surface), round(255 * self.opacity.value() / 100), 0)
        rgba = np.ascontiguousarray(np.flipud(rgba))
        image = QImage(
            rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format.Format_RGBA8888
        ).copy()
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        item.setScale(100 / surface.shape[1])
        item.setZValue(2)
        item.setData(1, "heatmap")
        self.scene.addItem(item)


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("WiFi Site Survey")
    window = SurveyWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
