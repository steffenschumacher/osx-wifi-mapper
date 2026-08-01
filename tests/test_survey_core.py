from __future__ import annotations

import io

import pytest
from PIL import Image

import wifi_site_survey as streamlit_app
from survey_core import SurveyDocument, measurement_frame, triple_eligibility


def image_bytes(size: tuple[int, int] = (200, 100)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, "PNG")
    return output.getvalue()


def readings() -> list[dict[str, object]]:
    return [{"ssid": "Home", "bssid": "AA", "band": "5 GHz", "rssi_dbm": -55, "channel": 44}]


def test_document_add_delete_and_round_trip() -> None:
    document = SurveyDocument(image_bytes(), "office.png", [(0.0, 0.0), (10.0, 0.0)], 0.5)
    point_id = document.add_measurement(12.0, 8.0, readings())
    restored = SurveyDocument.from_bytes(document.to_bytes())

    assert point_id == 1
    assert restored.y_max == 50.0
    assert restored.points == document.points
    assert restored.measurements == document.measurements
    restored.delete_point(1)
    assert restored.points == []
    assert restored.measurements == []


def test_native_loader_accepts_streamlit_v1_survey() -> None:
    points = [{"point_id": 1, "x": 2.0, "y": 3.0, "access_points": 1}]
    rows = [
        {
            "point_id": 1,
            "x": 2.0,
            "y": 3.0,
            "measured_at_utc": "2026-01-01T00:00:00+00:00",
            "ssid": "Home",
            "bssid": "AA",
            "band": "5 GHz",
            "rssi_dbm": -55,
            "channel": 44,
        }
    ]
    saved = streamlit_app.save_survey(
        image_bytes(), "office.png", [(0, 0), (10, 0)], 0.5, points, rows
    )
    restored = SurveyDocument.from_bytes(saved)
    assert restored.points == points
    assert restored.measurements == rows


def test_five_metric_points_are_eligible() -> None:
    document = SurveyDocument(image_bytes(), "office.png", meters_per_unit=1.0)
    for x, y in ((0, 0), (5, 0), (0, 5), (5, 5), (10, 5)):
        document.add_measurement(x, y, readings())
    result = triple_eligibility(measurement_frame(document.measurements), 1.0).iloc[0]
    assert bool(result["eligible"])


def test_document_rejects_invalid_archive() -> None:
    with pytest.raises(ValueError, match="not a valid"):
        SurveyDocument.from_bytes(b"invalid")
