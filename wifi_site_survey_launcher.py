"""Launcher used by PyInstaller release binaries."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_app_path() -> Path:
    """Return the app script from PyInstaller's bundle or the source tree."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / "wifi_site_survey.py"


def main() -> None:
    """Launch the bundled Streamlit application."""
    from streamlit.web import cli as stcli

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    sys.argv = [
        "streamlit",
        "run",
        str(bundled_app_path()),
        "--server.headless=false",
    ]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()
