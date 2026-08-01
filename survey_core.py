"""UI-independent survey model, persistence, filtering, and interpolation."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

MEASUREMENT_COLUMNS = [
    "point_id",
    "x",
    "y",
    "measured_at_utc",
    "ssid",
    "bssid",
    "band",
    "rssi_dbm",
    "channel",
]
TRIPLE_COLUMNS = ["ssid", "bssid", "band"]
MIN_HEATMAP_SAMPLES = 5
MIN_SAMPLE_DISTANCE_METERS = 1.0
RSSI_MIN = -90
RSSI_MAX = -40
SURVEY_FORMAT = "osx-wifi-mapper-survey"
SURVEY_FORMAT_VERSION = 1
SURVEY_MANIFEST = "survey.json"
SURVEY_IMAGE = "floorplan.bin"
MAX_SURVEY_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
Triple = tuple[str, str, str]


def _json_records(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        record = {}
        for key, value in row.items():
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, float) and not np.isfinite(value):
                value = None
            record[key] = (
                value
                if value is None or isinstance(value, str | int | float | bool)
                else str(value)
            )
        records.append(record)
    return records


@dataclass
class SurveyDocument:
    image_bytes: bytes
    image_name: str
    calibration_points: list[tuple[float, float]] = field(default_factory=list)
    meters_per_unit: float | None = None
    points: list[dict[str, Any]] = field(default_factory=list)
    measurements: list[dict[str, Any]] = field(default_factory=list)

    @property
    def next_point_id(self) -> int:
        return max((int(point["point_id"]) for point in self.points), default=0) + 1

    @property
    def image(self) -> Image.Image:
        return Image.open(io.BytesIO(self.image_bytes)).convert("RGB")

    @property
    def y_max(self) -> float:
        image = self.image
        return 100.0 * image.height / image.width

    def add_measurement(self, x: float, y: float, readings: list[dict[str, Any]]) -> int:
        point_id = self.next_point_id
        measured_at = datetime.now(timezone.utc).isoformat()
        point = {
            "point_id": point_id,
            "x": round(float(x), 2),
            "y": round(float(y), 2),
            "measured_at_utc": measured_at,
            "access_points": len(readings),
        }
        self.points.append(point)
        self.measurements.extend(
            {**{key: value for key, value in point.items() if key != "access_points"}, **reading}
            for reading in readings
        )
        return point_id

    def delete_point(self, point_id: int) -> None:
        self.points = [point for point in self.points if int(point["point_id"]) != point_id]
        self.measurements = [row for row in self.measurements if int(row["point_id"]) != point_id]

    def to_bytes(self) -> bytes:
        manifest = {
            "format": SURVEY_FORMAT,
            "version": SURVEY_FORMAT_VERSION,
            "image_file": SURVEY_IMAGE,
            "image_name": self.image_name,
            "image_sha256": hashlib.sha256(self.image_bytes).hexdigest(),
            "calibration_points": [list(map(float, point)) for point in self.calibration_points],
            "meters_per_unit": self.meters_per_unit,
            "points": _json_records(self.points),
            "measurements": _json_records(self.measurements),
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(SURVEY_MANIFEST, json.dumps(manifest, separators=(",", ":")))
            archive.writestr(SURVEY_IMAGE, self.image_bytes)
        return output.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> SurveyDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                entries = {entry.filename: entry for entry in infos}
                if len(infos) != 2 or set(entries) != {SURVEY_MANIFEST, SURVEY_IMAGE}:
                    raise ValueError("Survey archive has unexpected or missing files.")
                if sum(entry.file_size for entry in infos) > MAX_SURVEY_UNCOMPRESSED_BYTES:
                    raise ValueError("Survey archive is too large.")
                manifest = json.loads(archive.read(SURVEY_MANIFEST))
                image_bytes = archive.read(SURVEY_IMAGE)
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("The selected file is not a valid WiFi Site Survey.") from exc
        if not isinstance(manifest, dict):
            raise ValueError("Survey metadata is invalid.")
        if manifest.get("format") != SURVEY_FORMAT or manifest.get("version") != 1:
            raise ValueError("Unsupported survey file format or version.")
        if hashlib.sha256(image_bytes).hexdigest() != manifest.get("image_sha256"):
            raise ValueError("The floor-plan image in the survey is corrupted.")
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("The floor-plan image in the survey is invalid.") from exc
        calibration = manifest.get("calibration_points")
        points, measurements, scale = (
            manifest.get("points"),
            manifest.get("measurements"),
            manifest.get("meters_per_unit"),
        )
        if (
            not isinstance(calibration, list)
            or len(calibration) > 2
            or any(not isinstance(point, list) or len(point) != 2 for point in calibration)
            or not isinstance(points, list)
            or not isinstance(measurements, list)
            or any(not isinstance(point, dict) or "point_id" not in point for point in points)
            or any(
                not isinstance(row, dict) or not set(MEASUREMENT_COLUMNS).issubset(row)
                for row in measurements
            )
            or (
                scale is not None
                and (isinstance(scale, bool) or not isinstance(scale, int | float) or scale <= 0)
            )
        ):
            raise ValueError("Survey metadata is invalid.")
        return cls(
            image_bytes=image_bytes,
            image_name=str(manifest.get("image_name") or "floorplan"),
            calibration_points=[tuple(map(float, point)) for point in calibration],
            meters_per_unit=float(scale) if scale is not None else None,
            points=points,
            measurements=measurements,
        )


def save_survey(
    image_bytes: bytes,
    image_name: str,
    calibration_points: list[tuple[float, float]],
    meters_per_unit: float | None,
    points: Iterable[dict[str, Any]],
    measurements: Iterable[dict[str, Any]],
) -> bytes:
    """Serialize a survey through the shared versioned document model."""
    return SurveyDocument(
        image_bytes=image_bytes,
        image_name=image_name,
        calibration_points=calibration_points,
        meters_per_unit=meters_per_unit,
        points=list(points),
        measurements=list(measurements),
    ).to_bytes()


def load_survey(data: bytes) -> dict[str, Any]:
    """Load a survey into the dictionary shape used by the Streamlit UI."""
    document = SurveyDocument.from_bytes(data)
    return {
        "image_bytes": document.image_bytes,
        "image_name": document.image_name,
        "calibration_points": document.calibration_points,
        "meters_per_unit": document.meters_per_unit,
        "points": document.points,
        "measurements": document.measurements,
    }


def measurement_frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in MEASUREMENT_COLUMNS:
        if column not in frame:
            frame[column] = pd.Series(dtype="object")
    frame["band"] = frame["band"].fillna("Unknown")
    return frame[MEASUREMENT_COLUMNS]


def calibration_scale(
    start: tuple[float, float], end: tuple[float, float], distance_m: float
) -> float:
    coordinate_distance = float(np.linalg.norm(np.asarray(end) - np.asarray(start)))
    if coordinate_distance <= 0:
        raise ValueError("Calibration points must be different.")
    if distance_m <= 0:
        raise ValueError("Calibration distance must be greater than zero.")
    return distance_m / coordinate_distance


def has_spatial_spread(coordinates: np.ndarray) -> bool:
    if len(coordinates) < 3:
        return False
    singular = np.linalg.svd(coordinates - coordinates.mean(axis=0), compute_uv=False)
    return bool(len(singular) >= 2 and singular[0] > 1e-8 and singular[1] / singular[0] >= 0.02)


def spaced_coordinates(coordinates: np.ndarray, meters_per_unit: float) -> np.ndarray:
    accepted: list[np.ndarray] = []
    for coordinate in sorted(map(tuple, np.asarray(coordinates, dtype=float))):
        candidate = np.asarray(coordinate)
        if all(
            np.linalg.norm(candidate - prior) * meters_per_unit >= 1.0 - 1e-9 for prior in accepted
        ):
            accepted.append(candidate)
    return np.asarray(accepted, dtype=float).reshape((-1, 2))


def point_has_minimum_spacing(x: float, y: float, points: pd.DataFrame, scale: float) -> bool:
    if points.empty:
        return True
    distances = np.linalg.norm(points[["x", "y"]].to_numpy(dtype=float) - [x, y], axis=1)
    return bool(np.all(distances * scale >= 1.0 - 1e-9))


def triple_eligibility(measurements: pd.DataFrame, scale: float | None = None) -> pd.DataFrame:
    columns = [*TRIPLE_COLUMNS, "sample_count", "eligible", "reason"]
    records = []
    for triple, group in measurements.groupby(TRIPLE_COLUMNS, dropna=False, sort=True):
        unique = group[["x", "y"]].drop_duplicates().to_numpy(dtype=float)
        spaced = spaced_coordinates(unique, scale) if scale is not None else np.empty((0, 2))
        count, spread = len(spaced), has_spatial_spread(spaced)
        reason = (
            "distance calibration required"
            if scale is None
            else f"{count}/5 points"
            if count < 5
            else "insufficient spatial spread"
            if not spread
            else "Ready"
        )
        records.append(
            {
                **dict(zip(TRIPLE_COLUMNS, triple, strict=True)),
                "sample_count": count,
                "eligible": scale is not None and count >= 5 and spread,
                "reason": reason,
            }
        )
    return pd.DataFrame(records, columns=columns)


def select_eligible_triples(
    eligibility: pd.DataFrame, ssids: list[str], bssids: list[str], bands: list[str]
) -> list[Triple]:
    selected = eligibility[eligibility["eligible"]] if not eligibility.empty else eligibility
    for column, values in (("ssid", ssids), ("bssid", bssids), ("band", bands)):
        if values:
            selected = selected[selected[column].isin(values)]
    return [tuple(row) for row in selected[TRIPLE_COLUMNS].itertuples(index=False, name=None)]


def _convex_hull(points: np.ndarray) -> np.ndarray:
    unique = sorted({tuple(map(float, point)) for point in points})

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return np.asarray(lower[:-1] + upper[:-1])


def interpolate_rssi(
    coordinates: np.ndarray,
    values: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray | None = None,
    power: float = 2.0,
) -> np.ndarray:
    if y_axis is None:
        y_axis = x_axis
    grid_x, grid_y = np.meshgrid(x_axis, y_axis)
    if not has_spatial_spread(coordinates):
        return np.full_like(grid_x, np.nan)
    distance2 = (grid_x[..., None] - coordinates[:, 0]) ** 2 + (
        grid_y[..., None] - coordinates[:, 1]
    ) ** 2
    exact, safe = distance2 <= 1e-12, np.maximum(distance2, 1e-12)
    weights = 1.0 / np.power(safe, power / 2.0)
    surface = np.sum(weights * values, axis=2) / np.sum(weights, axis=2)
    cells, indices = exact.any(axis=2), exact.argmax(axis=2)
    surface[cells] = values[indices[cells]]
    hull, inside = _convex_hull(coordinates), np.ones_like(grid_x, dtype=bool)
    for start, end in zip(hull, np.roll(hull, -1, axis=0), strict=True):
        inside &= (end[0] - start[0]) * (grid_y - start[1]) - (end[1] - start[1]) * (
            grid_x - start[0]
        ) >= -1e-9
    surface[~inside] = np.nan
    return surface


def heatmap_surface(
    measurements: pd.DataFrame,
    triples: list[Triple],
    resolution: int = 101,
    y_max: float = 100.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    x_axis = np.linspace(0, 100, resolution)
    y_axis = np.linspace(0, y_max, max(2, round(resolution * y_max / 100)))
    surfaces = []
    for ssid, bssid, band in triples:
        group = measurements[
            (measurements.ssid == ssid)
            & (measurements.bssid == bssid)
            & (measurements.band == band)
        ]
        samples = group.groupby(["x", "y"], as_index=False).agg(rssi_dbm=("rssi_dbm", "max"))
        coords = samples[["x", "y"]].to_numpy(dtype=float)
        if len(coords) >= 5 and has_spatial_spread(coords):
            surfaces.append(
                interpolate_rssi(coords, samples.rssi_dbm.to_numpy(dtype=float), x_axis, y_axis)
            )
    if not surfaces:
        return x_axis, y_axis, None
    stacked = np.stack(surfaces)
    valid = np.isfinite(stacked)
    strongest = np.max(np.where(valid, stacked, -np.inf), axis=0)
    strongest[~valid.any(axis=0)] = np.nan
    return x_axis, y_axis, strongest
