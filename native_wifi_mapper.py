"""Responsive browser-free PySide6 application for Wi-Fi site surveys."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
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
    calibration_scale,
    heatmap_surface,
    measurement_frame,
    point_has_minimum_spacing,
    select_eligible_triples,
    triple_eligibility,
)

NATIVE_HEATMAP_RESOLUTION = 755
SAMPLE_MARKER_DIAMETER = 0.72


class SampleMarker(QGraphicsEllipseItem):
    """Compact selectable marker whose number appears only while hovered."""

    def __init__(self, x: float, y: float, point_id: int) -> None:
        radius = SAMPLE_MARKER_DIAMETER / 2
        super().__init__(x - radius, y - radius, SAMPLE_MARKER_DIAMETER, SAMPLE_MARKER_DIAMETER)
        self.setAcceptHoverEvents(True)
        self.number = QGraphicsSimpleTextItem(str(point_id), self)
        self.number.setBrush(QColor("white"))
        self.number.setScale(0.12)
        self.number.setPos(x - 0.7, y - 0.9)
        self.number.setZValue(1)
        self.number.setVisible(False)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.number.setVisible(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.number.setVisible(False)
        super().hoverLeaveEvent(event)


class MapView(QGraphicsView):
    map_clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._y_max = 100.0
        self._pan_position: QPoint | None = None

    def set_y_max(self, value: float) -> None:
        self._y_max = value

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            self._pan_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if any(
                item.flags() & item.GraphicsItemFlag.ItemIsSelectable
                for item in self.scene().items(point)
            ):
                super().mousePressEvent(event)
                return
            if 0 <= point.x() <= 100 and 0 <= point.y() <= self._y_max:
                self.map_clicked.emit(point.x(), self._y_max - point.y())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_position is not None:
            position = event.position().toPoint()
            delta = position - self._pan_position
            self._pan_position = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_position is not None and event.button() in {
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }:
            self._pan_position = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def fit_map(self) -> None:
        self.fitInView(0, 0, 100, self._y_max, Qt.AspectRatioMode.KeepAspectRatio)


class CalibrationDialog(QDialog):
    """Modal two-point distance calibration editor for a floor plan."""

    def __init__(self, document: SurveyDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Floor Plan Calibration")
        self.resize(900, 650)
        self.document = document
        self.calibration_points = list(document.calibration_points)
        self.meters_per_unit: float | None = None

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Click two endpoints of a known straight-line distance, then enter its real length."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.scene = QGraphicsScene(self)
        self.map_view = MapView()
        self.map_view.setScene(self.scene)
        self.map_view.set_y_max(document.y_max)
        self.map_view.map_clicked.connect(self.map_clicked)
        layout.addWidget(self.map_view, 1)
        form = QFormLayout()
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.01, 100000)
        existing_distance = self._existing_distance()
        self.distance_spin.setValue(existing_distance if existing_distance else 1.0)
        self.distance_spin.setSuffix(" m")
        self.distance_spin.valueChanged.connect(self.update_scale_preview)
        self.status_label = QLabel()
        form.addRow("Reference distance", self.distance_spin)
        form.addRow("Calculated scale", self.status_label)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._initialize_scene()

    def _existing_distance(self) -> float | None:
        if len(self.calibration_points) != 2 or not self.document.meters_per_unit:
            return None
        coordinate_distance = float(
            np.linalg.norm(
                np.asarray(self.calibration_points[1]) - np.asarray(self.calibration_points[0])
            )
        )
        return coordinate_distance * self.document.meters_per_unit

    def map_clicked(self, x: float, y: float) -> None:
        if len(self.calibration_points) == 2:
            self.calibration_points.clear()
        self.calibration_points.append((x, y))
        self._draw_alignment()

    def _initialize_scene(self) -> None:
        image = self.document.image.convert("RGBA")
        data = image.tobytes("raw", "RGBA")
        qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(qimage)
        background = self.scene.addPixmap(pixmap)
        background.setScale(100.0 / pixmap.width())
        self.scene.setSceneRect(0, 0, 100, self.document.y_max)
        self._draw_alignment()
        self.map_view.fit_map()

    def _draw_alignment(self) -> None:
        for item in self.scene.items():
            if item.data(0) == "calibration-overlay":
                self.scene.removeItem(item)
        points = [QPointF(x, self.document.y_max - y) for x, y in self.calibration_points]
        if len(points) == 2:
            line = self.scene.addLine(
                points[0].x(),
                points[0].y(),
                points[1].x(),
                points[1].y(),
                QPen(QColor("#7c3aed"), 0.8),
            )
            line.setData(0, "calibration-overlay")
            line.setZValue(2)
        for point in points:
            marker = self.scene.addEllipse(
                point.x() - 1,
                point.y() - 1,
                2,
                2,
                QPen(QColor("white"), 0.3),
                QColor("#7c3aed"),
            )
            marker.setData(0, "calibration-overlay")
            marker.setZValue(3)
        self.update_scale_preview()

    def update_scale_preview(self) -> None:
        valid = len(self.calibration_points) == 2
        self.meters_per_unit = None
        if valid:
            try:
                self.meters_per_unit = calibration_scale(
                    *self.calibration_points, self.distance_spin.value()
                )
            except ValueError:
                valid = False
        self.status_label.setText(
            f"{self.meters_per_unit:.6g} metres per coordinate unit"
            if self.meters_per_unit is not None
            else f"Select endpoint {len(self.calibration_points) + 1}"
            if len(self.calibration_points) < 2
            else "Endpoints must be different"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def accept(self) -> None:
        self.update_scale_preview()
        if self.meters_per_unit is not None:
            super().accept()


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


class HeatmapSignals(QObject):
    finished = Signal(int, object)


class HeatmapWorker(QRunnable):
    """Compute an RSSI surface without blocking Qt's GUI thread."""

    def __init__(
        self,
        generation: int,
        frame: pd.DataFrame,
        triples: list[tuple[str, str, str]],
        y_max: float,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.frame = frame
        self.triples = triples
        self.y_max = y_max
        self.signals = HeatmapSignals()

    @Slot()
    def run(self) -> None:
        _, _, surface = heatmap_surface(
            self.frame, self.triples, NATIVE_HEATMAP_RESOLUTION, self.y_max
        )
        self.signals.finished.emit(self.generation, surface)


class SurveyWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WiFi Site Survey — Native")
        self.resize(1200, 800)
        self.document: SurveyDocument | None = None
        self.pending_scan: tuple[float, float] | None = None
        self.location_manager = None
        self.thread_pool = QThreadPool.globalInstance()
        self.heatmap_generation = 0
        self.heatmap_surface_data: np.ndarray | None = None
        self.banner_generation = 0
        self.scene = QGraphicsScene(self)
        self.map_view = MapView()
        self.map_view.setScene(self.scene)
        self.map_view.map_clicked.connect(self.map_clicked)
        self.setCentralWidget(self.map_view)
        self._build_controls()
        self._build_menu()
        self.scan_banner = QLabel(self)
        self.scan_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_banner.setWordWrap(True)
        self.scan_banner.hide()
        self.statusBar().showMessage("Open a floor plan or saved survey to begin")
        self.refresh_location()
        self.update_stage_ui()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "scan_banner"):
            self.scan_banner.setGeometry(0, max(0, (self.height() - 90) // 2), self.width(), 90)

    def show_scan_banner(self, message: str, complete: bool = False) -> None:
        self.banner_generation += 1
        generation = self.banner_generation
        color = "#166534" if complete else "#1e3a8a"
        self.scan_banner.setStyleSheet(
            f"background: {color}; color: white; font-size: 18px; font-weight: bold; "
            "padding: 20px; border-top: 2px solid white; border-bottom: 2px solid white;"
        )
        self.scan_banner.setText(message)
        self.scan_banner.setGeometry(0, max(0, (self.height() - 90) // 2), self.width(), 90)
        self.scan_banner.show()
        self.scan_banner.raise_()
        if complete:
            QTimer.singleShot(5000, lambda: self.hide_scan_banner(generation))

    def hide_scan_banner(self, generation: int) -> None:
        if generation == self.banner_generation:
            self.scan_banner.hide()

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
        self.control_dock = dock
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.location_label = QLabel()
        self.location_button = QPushButton("Request Location Access")
        self.location_button.clicked.connect(self.request_location)
        layout.addWidget(self.location_label)
        layout.addWidget(self.location_button)
        self.calibration_status = QLabel("No calibrated floor plan")
        self.recalibrate_button = QPushButton("Recalibrate…")
        self.recalibrate_button.clicked.connect(self.recalibrate)
        layout.addWidget(self.calibration_status)
        layout.addWidget(self.recalibrate_button)
        filters = QGroupBox("Heatmap filters (none selected = all)")
        self.filters_group = filters
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
        self.opacity.valueChanged.connect(self.render_cached_heatmap)
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
            candidate = SurveyDocument(Path(path).read_bytes(), Path(path).name)
            self.clear_document()
            self.configure_calibration(candidate, initial=True)

    def open_survey(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Survey", "", "WiFi surveys (*.wifisurvey)"
        )
        if not path:
            return
        try:
            candidate = SurveyDocument.from_bytes(Path(path).read_bytes())
            if self.document_is_calibrated(candidate):
                self.activate_document(candidate)
            else:
                self.clear_document()
                self.configure_calibration(candidate, initial=True)
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid survey", str(exc))

    def create_calibration_dialog(self, document: SurveyDocument) -> CalibrationDialog:
        return CalibrationDialog(document, self)

    @staticmethod
    def document_is_calibrated(document: SurveyDocument | None) -> bool:
        if (
            not document
            or len(document.calibration_points) != 2
            or document.meters_per_unit is None
            or not np.isfinite(document.meters_per_unit)
            or document.meters_per_unit <= 0
        ):
            return False
        return bool(
            np.linalg.norm(
                np.asarray(document.calibration_points[1])
                - np.asarray(document.calibration_points[0])
            )
            > 1e-9
        )

    def configure_calibration(self, document: SurveyDocument, initial: bool) -> bool:
        dialog = self.create_calibration_dialog(document)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if initial:
                self.clear_document()
            return False
        document.calibration_points = list(dialog.calibration_points)
        document.meters_per_unit = dialog.meters_per_unit
        self.activate_document(document)
        return True

    def activate_document(self, document: SurveyDocument) -> None:
        self.document = document
        self.rebuild_scene()
        self.refresh_filters()
        self.update_stage_ui()
        self.statusBar().showMessage(
            f"Sampling stage ready — loaded {len(document.points)} existing points"
        )

    def clear_document(self) -> None:
        self.document = None
        self.pending_scan = None
        self.scene.clear()
        self.heatmap_surface_data = None
        for widget in (self.ssid_list, self.bssid_list, self.band_list):
            widget.clear()
        self.update_stage_ui()
        self.statusBar().showMessage(
            "Stage 1 of 2: open a floor plan and complete distance calibration"
        )

    def update_stage_ui(self) -> None:
        ready = self.document_is_calibrated(self.document)
        self.map_view.setEnabled(ready)
        self.recalibrate_button.setEnabled(ready)
        self.filters_group.setEnabled(ready)
        self.delete_button.setEnabled(ready)
        self.calibration_status.setText(
            f"Calibrated: {self.document.meters_per_unit:.6g} m/unit"
            if ready and self.document
            else "Stage 1: floor plan and calibration required"
        )

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
        if not self.document_is_calibrated(self.document):
            self.statusBar().showMessage(
                "Complete stage 1 (floor plan and calibration) before sampling"
            )
            return
        document = self.document
        if document is None or document.meters_per_unit is None:
            return
        points = pd.DataFrame(document.points)
        if not point_has_minimum_spacing(x, y, points, document.meters_per_unit):
            self.statusBar().showMessage("Measurement points must be at least one metre apart")
            return
        self.pending_scan = (x, y)
        self.set_controls_enabled(False)
        self.statusBar().showMessage("Scanning Wi-Fi networks…")
        self.show_scan_banner(
            "Scanning Wi-Fi networks…\n"
            "Please stay at this sample location and do not use other controls."
        )
        worker = ScanWorker()
        worker.signals.succeeded.connect(self.scan_succeeded)
        worker.signals.failed.connect(self.scan_failed)
        self.thread_pool.start(worker)

    def scan_succeeded(self, readings: object) -> None:
        if self.document and self.pending_scan:
            point_id = self.document.add_measurement(*self.pending_scan, readings)
            message = (
                f"Captured point {point_id}: {len(readings)} APs. "
                "Scan complete — you are now free to walk to the next sample location."
            )
            self.statusBar().showMessage(message)
            self.show_scan_banner(
                "Scan complete.\nYou are now free to walk to the next sample location.",
                complete=True,
            )
        self.pending_scan = None
        self.set_controls_enabled(True)
        self.refresh_filters()
        self.rebuild_scene()

    def scan_failed(self, message: str) -> None:
        self.pending_scan = None
        self.set_controls_enabled(True)
        self.scan_banner.hide()
        QMessageBox.warning(self, "Scan failed", message)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.map_view.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)
        self.control_dock.setEnabled(enabled)

    def recalibrate(self) -> None:
        if self.document:
            self.configure_calibration(self.document, initial=False)

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
        # Scene units are independent from raster pixels. Keep every source pixel
        # resident and scale the graphics item into the 100-unit map coordinate space.
        pixmap = QPixmap.fromImage(qimage)
        background = self.scene.addPixmap(pixmap)
        background.setScale(100.0 / pixmap.width())
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
            marker = SampleMarker(x, y, point_id)
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
        self.heatmap_generation += 1
        generation = self.heatmap_generation
        self.heatmap_surface_data = None
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
        if not triples:
            self.heatmap_surface_data = None
            return
        worker = HeatmapWorker(generation, frame, triples, self.document.y_max)
        worker.signals.finished.connect(self.heatmap_finished)
        self.thread_pool.start(worker)

    def heatmap_finished(self, generation: int, surface: object) -> None:
        if generation != self.heatmap_generation or not self.document:
            return
        self.heatmap_surface_data = surface
        self.render_cached_heatmap()

    def render_cached_heatmap(self) -> None:
        for item in self.scene.items():
            if item.data(1) == "heatmap":
                self.scene.removeItem(item)
        surface = self.heatmap_surface_data
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
