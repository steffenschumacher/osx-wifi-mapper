"""macOS Wi-Fi Site Survey.

Install and run on macOS:
    python3 -m pip install streamlit plotly pandas pillow \
        streamlit-plotly-events pyobjc-framework-CoreWLAN
    streamlit run wifi_site_survey.py

CoreWLAN scans may require Location Services permission. Grant location access to
the terminal (or Python host) running Streamlit in System Settings if SSIDs or
BSSIDs are hidden from the scan results.
"""

from __future__ import annotations

import hashlib
import io
import platform
from datetime import datetime, timezone
from typing import Any

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
    "rssi_dbm",
    "channel",
]


def scan_wifi() -> list[dict[str, Any]]:
    """Perform one synchronous scan with Apple's native CoreWLAN framework."""
    if platform.system() != "Darwin":
        raise RuntimeError("Live Wi-Fi scanning is available only on macOS.")

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
    for net in networks or []:
        channel = net.wlanChannel()
        results.append(
            {
                "ssid": str(net.ssid()) if net.ssid() is not None else "<hidden>",
                "bssid": (str(net.bssid()).upper() if net.bssid() is not None else "<unavailable>"),
                "rssi_dbm": int(net.rssiValue()),
                "channel": int(channel.channelNumber()) if channel else None,
            }
        )
    return results


def initialize_state() -> None:
    st.session_state.setdefault("points", [])
    st.session_state.setdefault("measurements", [])
    st.session_state.setdefault("next_point_id", 1)
    st.session_state.setdefault("map_revision", 0)
    st.session_state.setdefault("floorplan_hash", None)


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


def rssi_color(rssi: float) -> str:
    if rssi > -60:
        return "#22c55e"  # green
    if rssi >= -75:
        return "#facc15"  # yellow
    return "#ef4444"  # red


def build_map(
    image: Image.Image,
    visible_points: pd.DataFrame,
) -> go.Figure:
    """Build the floor-plan map; the transparent heatmap captures background clicks."""
    figure = go.Figure()
    figure.add_layout_image(
        source=image,
        xref="x",
        yref="y",
        x=0,
        y=100,
        sizex=100,
        sizey=100,
        sizing="stretch",
        opacity=1,
        layer="below",
    )

    # Plotly emits click events for traces, not bare layout images. A transparent
    # 101x101 heatmap makes every location clickable in relative 0–100 coordinates.
    grid = list(range(101))
    figure.add_trace(
        go.Heatmap(
            x=grid,
            y=grid,
            z=[[0] * 101 for _ in grid],
            opacity=0.01,
            showscale=False,
            hovertemplate="x=%{x:.0f}, y=%{y:.0f}<extra></extra>",
            name="Click to scan",
        )
    )

    if not visible_points.empty:
        figure.add_trace(
            go.Scatter(
                x=visible_points["x"],
                y=visible_points["y"],
                mode="markers",
                marker={
                    "size": 16,
                    "color": [rssi_color(value) for value in visible_points["rssi_dbm"]],
                    "line": {"color": "white", "width": 2},
                },
                customdata=visible_points[["point_id", "rssi_dbm", "access_points"]],
                hovertemplate=(
                    "Point %{customdata[0]}<br>x=%{x:.1f}, y=%{y:.1f}"
                    "<br>RSSI=%{customdata[1]:.1f} dBm"
                    "<br>Selected APs=%{customdata[2]}<extra></extra>"
                ),
                name="Measurements",
            )
        )

    figure.update_layout(
        height=700,
        margin={"l": 10, "r": 10, "t": 35, "b": 10},
        title="Click the floor plan to scan",
        showlegend=False,
        clickmode="event+select",
        dragmode=False,
        xaxis={"range": [0, 100], "title": "X", "fixedrange": True},
        yaxis={
            "range": [0, 100],
            "title": "Y",
            "fixedrange": True,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
    )
    return figure


def selected_point_summary(
    measurements: pd.DataFrame,
    selected_ssids: list[str],
    selected_bssids: list[str],
    aggregation: str,
) -> pd.DataFrame:
    if measurements.empty or not selected_ssids or not selected_bssids:
        return pd.DataFrame(columns=["point_id", "x", "y", "rssi_dbm", "access_points"])

    filtered = measurements[
        measurements["ssid"].isin(selected_ssids) & measurements["bssid"].isin(selected_bssids)
    ]
    if filtered.empty:
        return pd.DataFrame(columns=["point_id", "x", "y", "rssi_dbm", "access_points"])

    grouped = filtered.groupby(["point_id", "x", "y"], as_index=False)
    summary = grouped.agg(
        rssi_dbm=("rssi_dbm", "mean" if aggregation == "Average" else "max"),
        access_points=("bssid", "nunique"),
    )
    return summary


def main() -> None:  # pragma: no cover - Streamlit rerun orchestration
    st.set_page_config(page_title="macOS Wi-Fi Site Survey", layout="wide")
    initialize_state()
    st.title("macOS Wi-Fi Site Survey")
    st.caption("Upload a floor plan, then click a location to run a live CoreWLAN scan.")

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
        st.session_state.map_revision += 1

    try:
        floorplan = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        st.error(f"Could not read the floor plan: {exc}")
        return

    measurements = pd.DataFrame(st.session_state.measurements, columns=MEASUREMENT_COLUMNS)
    all_ssids = sorted(measurements["ssid"].dropna().unique().tolist())
    with st.sidebar:
        st.header("Signal filters")
        if measurements.empty:
            # Avoid creating empty persistent widgets before the first scan; once
            # data exists, Streamlit will correctly initialize every AP as active.
            st.caption("Filters become available after the first measurement.")
            selected_ssids: list[str] = []
            selected_bssids: list[str] = []
        else:
            selected_ssids = st.multiselect("SSID", all_ssids, default=all_ssids)
            eligible_bssids = sorted(
                measurements.loc[measurements["ssid"].isin(selected_ssids), "bssid"]
                .dropna()
                .unique()
                .tolist()
            )
            selected_bssids = st.multiselect("BSSID", eligible_bssids, default=eligible_bssids)
        aggregation = st.radio(
            "Multiple selected APs at one point",
            ["Strongest", "Average"],
            horizontal=True,
        )
        st.markdown(
            "**Signal colors**  \n🟢 above −60 dBm  \n🟡 −60 through −75 dBm  \n🔴 below −75 dBm"
        )

    visible_points = selected_point_summary(
        measurements, selected_ssids, selected_bssids, aggregation
    )
    figure = build_map(floorplan, visible_points)
    clicks = plotly_events(
        figure,
        click_event=True,
        select_event=False,
        hover_event=False,
        override_height=700,
        key=f"survey-map-{st.session_state.map_revision}",
    )

    if clicks:
        click = clicks[-1]
        try:
            with st.spinner("Scanning all visible Wi-Fi networks…"):
                point_id, count = add_measurement_point(click["x"], click["y"])
            st.session_state.map_revision += 1  # consume the component click event
            st.toast(f"Point {point_id}: captured {count} access point(s).")
            st.rerun()
        except Exception as exc:
            st.session_state.map_revision += 1  # allow a retry at the same location
            st.error(str(exc))

    st.subheader("Manage Points")
    points = pd.DataFrame(st.session_state.points)
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
            st.session_state.points = [
                point for point in st.session_state.points if point["point_id"] != point_id
            ]
            st.session_state.measurements = [
                row for row in st.session_state.measurements if row["point_id"] != point_id
            ]
            st.session_state.map_revision += 1
            st.rerun()

    st.subheader("Export")
    export_frame = pd.DataFrame(st.session_state.measurements, columns=MEASUREMENT_COLUMNS)
    st.download_button(
        "Download survey CSV",
        data=export_frame.to_csv(index=False).encode("utf-8"),
        file_name="wifi_site_survey.csv",
        mime="text/csv",
        disabled=export_frame.empty,
    )


if __name__ == "__main__":
    main()
