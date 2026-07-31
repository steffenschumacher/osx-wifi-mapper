from __future__ import annotations

from pathlib import Path

import wifi_site_survey_launcher as launcher


def test_source_app_path_exists() -> None:
    path = launcher.bundled_app_path()
    assert path == Path(launcher.__file__).resolve().parent / "wifi_site_survey.py"
    assert path.is_file()
