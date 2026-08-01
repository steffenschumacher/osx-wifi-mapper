"""macOS Wi-Fi Site Survey.

Install and run on macOS:
    python3 -m pip install streamlit plotly pandas numpy pillow \
        streamlit-plotly-events pyobjc-framework-CoreWLAN
    streamlit run wifi_site_survey.py

CoreWLAN scans may require Location Services permission. Grant location access to
the terminal (or Python host) running Streamlit in System Settings if SSIDs or
BSSIDs are hidden from the scan results.
"""

from __future__ import annotations

import hashlib
import html
import io
import platform
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image
from streamlit_plotly_events import plotly_events

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
RSSI_COLORSCALE = [
    [0.0, "#ef4444"],
    [0.30, "#ef4444"],  # -75 dBm
    [0.50, "#facc15"],  # -65 dBm
    [0.60, "#facc15"],  # -60 dBm
    [0.80, "#22c55e"],
    [1.0, "#22c55e"],
]
Triple = tuple[str, str, str]
LOCATION_AUTHORIZED = {3, 4}
LOCATION_STATUS_NAMES = {
    0: "Not requested",
    1: "Restricted",
    2: "Denied",
    3: "Authorized",
    4: "Authorized while in use",
}


def location_authorization() -> tuple[int | None, Any | None]:
    """Return Core Location authorization and a retained manager on macOS."""
    if platform.system() != "Darwin":
        return None, None
    try:
        from objc import loadBundle

        loadBundle(
            "CoreLocation",
            bundle_path="/System/Library/Frameworks/CoreLocation.framework",
            module_globals=globals(),
        )
        manager = CLLocationManager.alloc().init()  # noqa: F821 - injected by loadBundle
        return int(manager.authorizationStatus()), manager
    except Exception:
        return None, None


def request_location_authorization() -> tuple[int | None, Any | None]:
    """Bring a frozen app forward and request macOS Location Services access."""
    status, manager = location_authorization()
    if manager is None or status != 0:
        return status, manager
    if getattr(sys, "frozen", False):
        try:
            from AppKit import NSApplication

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except ImportError:
            pass
    manager.requestWhenInUseAuthorization()
    return status, manager


def location_permission_error(status: int | None) -> str | None:
    """Return actionable scan-blocking guidance for a location authorization state."""
    if status in LOCATION_AUTHORIZED:
        return None
    if status == 0:
        return "Location access has not been granted. Use 'Request Location Access' first."
    if status in {1, 2}:
        return (
            "Location access is denied. Enable WiFi Site Survey (or your terminal when running "
            "from source) in System Settings → Privacy & Security → Location Services."
        )
    return "Core Location authorization could not be checked; SSID and BSSID cannot be read safely."


def normalize_band(value: Any) -> str:
    """Normalize CoreWLAN's CWChannelBand enum to a stable display value."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = None
    return {1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}.get(numeric, "Unknown")


def scan_wifi() -> list[dict[str, Any]]:
    """Perform one synchronous scan with Apple's native CoreWLAN framework."""
    if platform.system() != "Darwin":
        raise RuntimeError("Live Wi-Fi scanning is available only on macOS.")
    permission_error = location_permission_error(location_authorization()[0])
    if permission_error:
        raise RuntimeError(permission_error)

    # Import lazily so the UI can still start and explain missing dependencies.
    try:
        from objc import loadBundle

        loadBundle(
            "CoreWLAN",
            bundle_path="/System/Library/Frameworks/CoreWLAN.framework",
            module_globals=globals(),
        )
        client = CWWiFiClient.sharedWiFiClient()  # noqa: F821 - injected by loadBundle
        interface = client.interface()
        if interface is None:
            raise RuntimeError("CoreWLAN could not find a Wi-Fi interface.")

        networks, error = interface.scanForNetworksWithName_error_(None, None)
    except ImportError as exc:
        raise RuntimeError(
            "PyObjC CoreWLAN support is missing. Install pyobjc-framework-CoreWLAN."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"CoreWLAN scan failed: {exc}") from exc

    if error is not None:
        raise RuntimeError(f"CoreWLAN scan failed: {error}")

    results: list[dict[str, Any]] = []
    redacted = 0
    for net in networks or []:
        channel = net.wlanChannel()
        try:
            band = normalize_band(channel.channelBand()) if channel else "Unknown"
        except (AttributeError, TypeError, ValueError):
            band = "Unknown"
        ssid = str(net.ssid()) if net.ssid() is not None else "<hidden>"
        bssid = str(net.bssid()).upper() if net.bssid() is not None else "<unavailable>"
        if net.ssid() is None and net.bssid() is None:
            redacted += 1
        results.append(
            {
                "ssid": ssid,
                "bssid": bssid,
                "band": band,
                "rssi_dbm": int(net.rssiValue()),
                "channel": int(channel.channelNumber()) if channel else None,
            }
        )
    if results and redacted == len(results):
        raise RuntimeError(
            "macOS redacted every SSID and BSSID. Grant this app Location Services access, "
            "then quit it completely, reopen it, and scan again. Do not run it with sudo."
        )
    return results


def initialize_state() -> None:
    st.session_state.setdefault("points", [])
    st.session_state.setdefault("measurements", [])
    st.session_state.setdefault("next_point_id", 1)
    st.session_state.setdefault("map_revision", 0)
    st.session_state.setdefault("floorplan_hash", None)
    st.session_state.setdefault("location_manager", None)
    st.session_state.setdefault("calibration_points", [])
    st.session_state.setdefault("meters_per_unit", None)


def add_measurement_point(x: float, y: float) -> tuple[int, int]:
    """Scan once and atomically add a point and all AP readings."""
    readings = scan_wifi()
    point_id = st.session_state.next_point_id
    measured_at = datetime.now(timezone.utc).isoformat()
    point = {
        "point_id": point_id,
        "x": round(float(x), 2),
        "y": round(float(y), 2),
        "measured_at_utc": measured_at,
        "access_points": len(readings),
    }
    rows = [{**point, **reading} for reading in readings]
    for row in rows:
        row.pop("access_points", None)

    st.session_state.points.append(point)
    st.session_state.measurements.extend(rows)
    st.session_state.next_point_id += 1
    return point_id, len(readings)


def delete_measurement_point(point_id: int) -> None:
    """Delete a point and all of its AP readings from session state."""
    st.session_state.points = [
        point for point in st.session_state.points if point["point_id"] != point_id
    ]
    st.session_state.measurements = [
        row for row in st.session_state.measurements if row["point_id"] != point_id
    ]
    st.session_state.map_revision += 1


def rssi_color(rssi: float) -> str:
    if rssi > -60:
        return "#22c55e"  # green
    if rssi >= -75:
        return "#facc15"  # yellow
    return "#ef4444"  # red


def measurement_frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Create a stable export/filter frame, including compatibility for old session rows."""
    frame = pd.DataFrame(rows)
    for column in MEASUREMENT_COLUMNS:
        if column not in frame:
            frame[column] = pd.Series(dtype="object")
    frame["band"] = frame["band"].fillna("Unknown")
    return frame[MEASUREMENT_COLUMNS]


def _has_spatial_spread(coordinates: np.ndarray) -> bool:
    """Return whether coordinates span a genuine two-dimensional area."""
    if len(coordinates) < 3:
        return False
    centered = coordinates - coordinates.mean(axis=0)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    return bool(
        len(singular_values) >= 2
        and singular_values[0] > 1e-8
        and singular_values[1] / singular_values[0] >= 0.02
    )


def calibration_scale(
    start: tuple[float, float], end: tuple[float, float], real_distance_meters: float
) -> float:
    """Return metres per map-coordinate unit for a measured reference line."""
    coordinate_distance = float(np.linalg.norm(np.asarray(end) - np.asarray(start)))
    if coordinate_distance <= 0:
        raise ValueError("Calibration points must be different.")
    if real_distance_meters <= 0:
        raise ValueError("Calibration distance must be greater than zero.")
    return float(real_distance_meters) / coordinate_distance


def spaced_coordinates(
    coordinates: np.ndarray,
    meters_per_unit: float,
    minimum_distance_meters: float = MIN_SAMPLE_DISTANCE_METERS,
) -> np.ndarray:
    """Return a deterministic subset whose points are at least the requested distance apart."""
    accepted: list[np.ndarray] = []
    for coordinate in sorted(map(tuple, np.asarray(coordinates, dtype=float))):
        candidate = np.asarray(coordinate, dtype=float)
        if all(
            np.linalg.norm(candidate - existing) * meters_per_unit >= minimum_distance_meters - 1e-9
            for existing in accepted
        ):
            accepted.append(candidate)
    return np.asarray(accepted, dtype=float).reshape((-1, 2))


def point_has_minimum_spacing(
    x: float,
    y: float,
    points: pd.DataFrame,
    meters_per_unit: float,
) -> bool:
    """Return whether a prospective sample is at least one metre from every existing point."""
    if points.empty:
        return True
    distances = np.linalg.norm(points[["x", "y"]].to_numpy(dtype=float) - [x, y], axis=1)
    return bool(np.all(distances * meters_per_unit >= MIN_SAMPLE_DISTANCE_METERS - 1e-9))


def triple_eligibility(
    measurements: pd.DataFrame, meters_per_unit: float | None = None
) -> pd.DataFrame:
    """Describe heatmap eligibility for every observed SSID/BSSID/band triple."""
    columns = [*TRIPLE_COLUMNS, "sample_count", "eligible", "reason"]
    if measurements.empty:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, Any]] = []
    for triple, group in measurements.groupby(TRIPLE_COLUMNS, dropna=False, sort=True):
        unique_points = group[["x", "y"]].drop_duplicates().to_numpy(dtype=float)
        spaced_points = (
            spaced_coordinates(unique_points, meters_per_unit)
            if meters_per_unit is not None
            else np.empty((0, 2))
        )
        sample_count = len(spaced_points)
        spatially_valid = _has_spatial_spread(spaced_points)
        if meters_per_unit is None:
            reason = "distance calibration required"
        elif sample_count < MIN_HEATMAP_SAMPLES:
            reason = f"{sample_count}/{MIN_HEATMAP_SAMPLES} points"
        elif not spatially_valid:
            reason = "insufficient spatial spread"
        else:
            reason = "Ready"
        records.append(
            {
                **dict(zip(TRIPLE_COLUMNS, triple, strict=True)),
                "sample_count": sample_count,
                "eligible": (
                    meters_per_unit is not None
                    and sample_count >= MIN_HEATMAP_SAMPLES
                    and spatially_valid
                ),
                "reason": reason,
            }
        )
    return pd.DataFrame(records, columns=columns)


def select_eligible_triples(
    eligibility: pd.DataFrame,
    ssids: list[str],
    bssids: list[str],
    bands: list[str],
) -> list[Triple]:
    """Return eligible triples matching each independently optional filter."""
    if eligibility.empty:
        return []
    selected = eligibility[eligibility["eligible"]]
    if ssids:
        selected = selected[selected["ssid"].isin(ssids)]
    if bssids:
        selected = selected[selected["bssid"].isin(bssids)]
    if bands:
        selected = selected[selected["band"].isin(bands)]
    return [tuple(row) for row in selected[TRIPLE_COLUMNS].itertuples(index=False, name=None)]


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Return the convex hull vertices in counter-clockwise order."""
    unique = sorted({(float(x), float(y)) for x, y in points})
    if len(unique) < 3:
        return np.asarray(unique, dtype=float)

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

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
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def _inside_convex_polygon(grid_x: np.ndarray, grid_y: np.ndarray, hull: np.ndarray) -> np.ndarray:
    """Vectorized inclusive point-in-convex-polygon test for a grid."""
    if len(hull) < 3:
        return np.zeros_like(grid_x, dtype=bool)
    inside = np.ones_like(grid_x, dtype=bool)
    for start, end in zip(hull, np.roll(hull, -1, axis=0), strict=True):
        cross = (end[0] - start[0]) * (grid_y - start[1]) - (end[1] - start[1]) * (
            grid_x - start[0]
        )
        inside &= cross >= -1e-9
    return inside


def interpolate_rssi(
    coordinates: np.ndarray,
    values: np.ndarray,
    grid_x_axis: np.ndarray,
    grid_y_axis: np.ndarray | None = None,
    power: float = 2.0,
) -> np.ndarray:
    """Interpolate RSSI with IDW and mask cells outside the sampled convex hull."""
    coordinates = np.asarray(coordinates, dtype=float)
    values = np.asarray(values, dtype=float)
    if grid_y_axis is None:
        grid_y_axis = grid_x_axis
    grid_x, grid_y = np.meshgrid(grid_x_axis, grid_y_axis)
    if not _has_spatial_spread(coordinates):
        return np.full_like(grid_x, np.nan, dtype=float)

    dx = grid_x[..., None] - coordinates[:, 0]
    dy = grid_y[..., None] - coordinates[:, 1]
    distance_squared = dx * dx + dy * dy
    exact = distance_squared <= 1e-12
    safe_distance = np.maximum(distance_squared, 1e-12)
    weights = 1.0 / np.power(safe_distance, power / 2.0)
    surface = np.sum(weights * values, axis=2) / np.sum(weights, axis=2)
    if exact.any():
        exact_cells = exact.any(axis=2)
        exact_indices = exact.argmax(axis=2)
        surface[exact_cells] = values[exact_indices[exact_cells]]

    hull = _convex_hull(coordinates)
    surface[~_inside_convex_polygon(grid_x, grid_y, hull)] = np.nan
    return surface


def combine_surfaces(surfaces: list[np.ndarray]) -> np.ndarray | None:
    """Combine selected triple surfaces using strongest (maximum) RSSI per cell."""
    if not surfaces:
        return None
    stacked = np.stack(surfaces)
    valid = np.isfinite(stacked)
    strongest = np.max(np.where(valid, stacked, -np.inf), axis=0)
    strongest[~valid.any(axis=0)] = np.nan
    return strongest


def heatmap_surface(
    measurements: pd.DataFrame,
    selected_triples: list[Triple],
    resolution: int = 101,
    y_max: float = 100.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Interpolate eligible triples independently and combine them by strongest RSSI."""
    grid_x_axis = np.linspace(0.0, 100.0, resolution)
    y_resolution = max(2, round(resolution * y_max / 100.0))
    grid_y_axis = np.linspace(0.0, y_max, y_resolution)
    surfaces: list[np.ndarray] = []
    for ssid, bssid, band in selected_triples:
        group = measurements[
            (measurements["ssid"] == ssid)
            & (measurements["bssid"] == bssid)
            & (measurements["band"] == band)
        ]
        samples = group.groupby(["x", "y"], as_index=False).agg(rssi_dbm=("rssi_dbm", "max"))
        coordinates = samples[["x", "y"]].to_numpy(dtype=float)
        if len(coordinates) < MIN_HEATMAP_SAMPLES or not _has_spatial_spread(coordinates):
            continue
        surfaces.append(
            interpolate_rssi(
                coordinates,
                samples["rssi_dbm"].to_numpy(dtype=float),
                grid_x_axis,
                grid_y_axis,
            )
        )
    return grid_x_axis, grid_y_axis, combine_surfaces(surfaces)


def image_y_max(image: Image.Image) -> float:
    """Return the image height in isotropic width-normalized map coordinates."""
    return 100.0 * image.height / image.width


def map_height(image: Image.Image) -> int:
    """Return a practical Plotly height while retaining the image aspect ratio."""
    return max(350, min(900, round(700 * image.height / image.width)))


def click_coordinates(
    click: dict[str, Any], x_axis: np.ndarray, y_axis: np.ndarray
) -> tuple[float, float]:
    """Extract map coordinates from Plotly click data, including heatmap point-index fallback."""
    if "x" in click and "y" in click:
        return float(click["x"]), float(click["y"])
    point_number = click.get("pointNumber")
    if isinstance(point_number, (list, tuple)) and len(point_number) == 2:
        row, column = map(int, point_number)
        return float(x_axis[column]), float(y_axis[row])
    raise ValueError("The map click did not include usable coordinates. Please click again.")


def format_hover_readings(group: pd.DataFrame) -> str:
    """Format every AP reading at a point for Plotly marker hover text."""
    if group.empty:
        return "No access points captured"
    ordered = group.sort_values(["ssid", "bssid", "band", "channel"], na_position="last")
    readings = []
    for row in ordered.itertuples():
        channel = "Unknown" if pd.isna(row.channel) else str(int(row.channel))
        ssid = html.escape(str(row.ssid))
        bssid = html.escape(str(row.bssid))
        band = html.escape(str(row.band))
        readings.append(f"{ssid} / {bssid} / {band} / channel {channel}: {int(row.rssi_dbm)} dBm")
    return "<br>".join(readings)


def marker_frame(points: pd.DataFrame, measurements: pd.DataFrame) -> pd.DataFrame:
    """Build one marker per measured coordinate with all readings in hover text."""
    if points.empty:
        return pd.DataFrame(columns=["point_id", "x", "y", "hover"])
    result = points[["point_id", "x", "y"]].copy()
    grouped = {point_id: group for point_id, group in measurements.groupby("point_id")}
    result["hover"] = [
        format_hover_readings(grouped.get(point_id, pd.DataFrame()))
        for point_id in result["point_id"]
    ]
    return result


def build_map(
    image: Image.Image,
    markers: pd.DataFrame,
    grid_x_axis: np.ndarray | None = None,
    grid_y_axis: np.ndarray | None = None,
    surface: np.ndarray | None = None,
    heatmap_opacity: float = 0.55,
    calibration_points: list[tuple[float, float]] | None = None,
) -> go.Figure:
    """Build the clickable floor-plan, RSSI overlay, and sample markers."""
    figure = go.Figure()
    y_max = image_y_max(image)
    figure.add_layout_image(
        source=image,
        xref="x",
        yref="y",
        x=0,
        y=y_max,
        sizex=100,
        sizey=y_max,
        sizing="stretch",
        opacity=1,
        layer="below",
    )

    # Plotly emits click events for traces, not bare layout images. Keep a nearly
    # transparent heatmap above the image so clicks are reliably hit-tested.
    grid_x = np.linspace(0.0, 100.0, 101)
    grid_y = np.linspace(0.0, y_max, max(2, round(y_max) + 1))
    figure.add_trace(
        go.Heatmap(
            x=grid_x.tolist(),
            y=grid_y.tolist(),
            z=np.zeros((len(grid_y), len(grid_x))).tolist(),
            colorscale=[[0.0, "rgba(255,255,255,0.01)"], [1.0, "rgba(255,255,255,0.01)"]],
            opacity=1.0,
            showscale=False,
            hovertemplate="x=%{x:.0f}, y=%{y:.0f}<extra></extra>",
            name="Click to scan",
        )
    )

    if surface is not None and grid_x_axis is not None and grid_y_axis is not None:
        figure.add_trace(
            go.Heatmap(
                # streamlit-plotly-events does not reliably decode Plotly 6's binary
                # typed-array representation, so keep component payloads as JSON lists.
                x=grid_x_axis.tolist(),
                y=grid_y_axis.tolist(),
                z=surface.tolist(),
                zmin=RSSI_MIN,
                zmax=RSSI_MAX,
                colorscale=RSSI_COLORSCALE,
                opacity=heatmap_opacity,
                colorbar={"title": {"text": "RSSI<br>dBm"}},
                hovertemplate="RSSI=%{z:.1f} dBm<extra></extra>",
                name="Strongest selected signal",
                zsmooth="best",
            )
        )

    if calibration_points:
        calibration = np.asarray(calibration_points, dtype=float)
        figure.add_trace(
            go.Scatter(
                x=calibration[:, 0].tolist(),
                y=calibration[:, 1].tolist(),
                mode="lines+markers",
                line={"color": "#7c3aed", "width": 4},
                marker={"color": "#7c3aed", "size": 12},
                hovertemplate="Calibration endpoint<extra></extra>",
                name="Calibration line",
            )
        )

    if not markers.empty:
        figure.add_trace(
            go.Scatter(
                x=markers["x"],
                y=markers["y"],
                mode="markers",
                marker={
                    "size": 14,
                    "symbol": "diamond",
                    "color": "#2563eb",
                    "line": {"color": "white", "width": 2},
                },
                customdata=markers[["point_id", "hover"]],
                hovertemplate=(
                    "Point %{customdata[0]}<br>x=%{x:.1f}, y=%{y:.1f}"
                    "<br>%{customdata[1]}<extra></extra>"
                ),
                name="Sample points",
            )
        )

    figure.update_layout(
        height=map_height(image),
        margin={"l": 10, "r": 10, "t": 35, "b": 10},
        title=(
            "Click two endpoints to calibrate distance"
            if calibration_points is not None and len(calibration_points) < 2
            else "Click the floor plan to scan"
        ),
        showlegend=False,
        clickmode="event+select",
        dragmode=False,
        xaxis={"range": [0, 100], "title": "X", "fixedrange": True},
        yaxis={
            "range": [0, y_max],
            "title": "Y",
            "fixedrange": True,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
    )
    return figure


def main() -> None:  # pragma: no cover - Streamlit rerun orchestration
    st.set_page_config(page_title="macOS Wi-Fi Site Survey", layout="wide")
    initialize_state()
    st.title("macOS Wi-Fi Site Survey")
    st.caption("Upload a floor plan, then click a location to run a live CoreWLAN scan.")

    if platform.system() == "Darwin":
        location_status, manager = location_authorization()
        status_name = LOCATION_STATUS_NAMES.get(location_status, "Unavailable")
        with st.expander(
            "Required: Location Services access for SSID and BSSID",
            expanded=location_status not in LOCATION_AUTHORIZED,
        ):
            st.write(
                "macOS treats Wi-Fi network names and access-point addresses as location data. "
                "Without permission it returns redacted values, even though RSSI and channel "
                "remain visible. Administrator or sudo access does not bypass this requirement."
            )
            st.write(f"**Current authorization:** {status_name}")
            if location_status in LOCATION_AUTHORIZED:
                st.success("Location access is ready for SSID/BSSID scans.")
            elif getattr(sys, "frozen", False) and location_status == 0:
                if st.button("Request Location Access"):
                    _, requested_manager = request_location_authorization()
                    st.session_state.location_manager = requested_manager
                    st.info(
                        "Respond to the macOS permission dialog, then quit and reopen the app "
                        "before scanning."
                    )
            else:
                st.warning(
                    "Open System Settings → Privacy & Security → Location Services and enable "
                    "WiFi Site Survey. When running from source, enable the terminal or IDE that "
                    "starts Streamlit. Quit and reopen it after changing access."
                )
            if manager is not None and st.session_state.location_manager is None:
                st.session_state.location_manager = manager

    uploaded = st.file_uploader("Floor plan", type=["png", "jpg", "jpeg"])
    if uploaded is None:
        st.info("Upload a PNG or JPG floor plan to begin.")
        return

    image_bytes = uploaded.getvalue()
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    if st.session_state.floorplan_hash != image_hash:
        st.session_state.floorplan_hash = image_hash
        st.session_state.points = []
        st.session_state.measurements = []
        st.session_state.next_point_id = 1
        st.session_state.calibration_points = []
        st.session_state.meters_per_unit = None
        st.session_state.map_revision += 1

    try:
        floorplan = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        st.error(f"Could not read the floor plan: {exc}")
        return

    y_max = image_y_max(floorplan)
    measurements = measurement_frame(st.session_state.measurements)
    points = pd.DataFrame(st.session_state.points)
    eligibility = triple_eligibility(measurements, st.session_state.meters_per_unit)
    eligible = eligibility[eligibility["eligible"]]
    with st.sidebar:
        st.header("Distance calibration")
        calibration_points = st.session_state.calibration_points
        if st.session_state.meters_per_unit is None:
            if len(calibration_points) < 2:
                st.warning(
                    "Click two endpoints of a known straight-line distance on the floor plan."
                )
                if calibration_points:
                    first_x, first_y = calibration_points[0]
                    st.info(
                        f"First endpoint recorded at ({first_x:.1f}, {first_y:.1f}). "
                        "Now click the second endpoint."
                    )
                else:
                    st.info("Waiting for the first endpoint click.")
            else:
                real_distance = st.number_input(
                    "Reference distance (metres)", min_value=0.01, value=1.0, step=0.1
                )
                if st.button("Apply calibration", type="primary"):
                    st.session_state.meters_per_unit = calibration_scale(
                        tuple(calibration_points[0]), tuple(calibration_points[1]), real_distance
                    )
                    st.session_state.map_revision += 1
                    st.rerun()
        else:
            units_per_meter = 1.0 / st.session_state.meters_per_unit
            st.success(f"Calibrated: {units_per_meter:.2f} map units per metre")
            if st.button("Recalibrate"):
                st.session_state.calibration_points = []
                st.session_state.meters_per_unit = None
                st.session_state.map_revision += 1
                st.rerun()

        st.header("Heatmap filters")
        if eligible.empty:
            st.caption(
                f"A network needs {MIN_HEATMAP_SAMPLES} samples, each at least "
                f"{MIN_SAMPLE_DISTANCE_METERS:g} m apart, with two-dimensional spread."
            )
            selected_ssids: list[str] = []
            selected_bssids: list[str] = []
            selected_bands: list[str] = []
        else:
            selected_ssids = st.multiselect("SSID", sorted(eligible["ssid"].unique()))
            selected_bssids = st.multiselect("BSSID", sorted(eligible["bssid"].unique()))
            selected_bands = st.multiselect("Band", sorted(eligible["band"].unique()))
            st.caption("Leave a filter empty to include all of its values.")
        heatmap_opacity = st.slider("Heatmap opacity", 0.1, 0.9, 0.55, 0.05)
        st.markdown(
            "**Fixed RSSI scale**  \n🟢 strong  \n🟡 intermediate  \n🔴 weak  \n"
            "Range: −90 to −40 dBm"
        )
        ineligible = eligibility[~eligibility["eligible"]]
        if not ineligible.empty:
            with st.expander("Networks not ready for heatmaps"):
                for row in ineligible.itertuples():
                    st.caption(f"{row.ssid} / {row.bssid} / {row.band} — {row.reason}")

    selected_triples = select_eligible_triples(
        eligibility, selected_ssids, selected_bssids, selected_bands
    )
    grid_x_axis, grid_y_axis, surface = heatmap_surface(measurements, selected_triples, y_max=y_max)
    markers = marker_frame(points, measurements)
    if st.session_state.meters_per_unit is None:
        st.info("Calibrate the floor plan before collecting measurement points.")
    elif eligible.empty:
        st.info(
            f"Collect at least {MIN_HEATMAP_SAMPLES} samples at least "
            f"{MIN_SAMPLE_DISTANCE_METERS:g} m apart for a network."
        )
    figure = build_map(
        floorplan,
        markers,
        grid_x_axis,
        grid_y_axis,
        surface,
        heatmap_opacity,
        st.session_state.calibration_points,
    )
    plot_height = map_height(floorplan)
    clicks = plotly_events(
        figure,
        click_event=True,
        select_event=False,
        hover_event=False,
        override_height=plot_height,
        key=f"survey-map-{st.session_state.map_revision}",
    )

    if clicks:
        click = clicks[-1]
        try:
            click_x_axis = np.linspace(0.0, 100.0, 101)
            click_y_axis = np.linspace(0.0, y_max, max(2, round(y_max) + 1))
            x, y = click_coordinates(click, click_x_axis, click_y_axis)
            if st.session_state.meters_per_unit is None:
                if len(st.session_state.calibration_points) >= 2:
                    st.session_state.calibration_points = []
                st.session_state.calibration_points = [
                    *st.session_state.calibration_points,
                    (x, y),
                ]
                st.session_state.map_revision += 1
            elif not point_has_minimum_spacing(x, y, points, st.session_state.meters_per_unit):
                st.session_state.map_revision += 1
                st.error(
                    f"Measurement points must be at least {MIN_SAMPLE_DISTANCE_METERS:g} metre "
                    "apart. Choose another location."
                )
                return
            else:
                with st.spinner("Scanning all visible Wi-Fi networks…"):
                    point_id, count = add_measurement_point(x, y)
                st.session_state.map_revision += 1  # consume the component click event
                st.toast(f"Point {point_id}: captured {count} access point(s).")
            st.rerun()
        except Exception as exc:
            st.session_state.map_revision += 1  # allow a retry at the same location
            st.error(str(exc))

    st.subheader("Manage Points")
    if points.empty:
        st.caption("No measurement points yet.")
    else:
        st.dataframe(points, hide_index=True, use_container_width=True)
        labels = {
            f"Point {int(row.point_id)} — ({row.x:.1f}, {row.y:.1f}), "
            f"{int(row.access_points)} AP(s)": int(row.point_id)
            for row in points.itertuples()
        }
        chosen = st.selectbox("Point to delete", labels.keys())
        if st.button("Delete selected point", type="secondary"):
            point_id = labels[chosen]
            delete_measurement_point(point_id)
            st.rerun()

    st.subheader("Export")
    export_frame = measurement_frame(st.session_state.measurements)
    st.download_button(
        "Download survey CSV",
        data=export_frame.to_csv(index=False).encode("utf-8"),
        file_name="wifi_site_survey.csv",
        mime="text/csv",
        disabled=export_frame.empty,
    )


if __name__ == "__main__":
    main()
