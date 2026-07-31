"""Launcher used by PyInstaller release binaries."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8501
HEALTH_PATH = "/_stcore/health"


def bundled_app_path() -> Path:
    """Return the app script from PyInstaller's bundle or the source tree."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / "wifi_site_survey.py"


def server_port() -> int:
    """Return the requested port, falling back to a free loopback port if needed."""
    configured = int(os.environ.get("WIFI_SITE_SURVEY_PORT", DEFAULT_PORT))
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", configured))
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])
    return configured


def open_browser_when_ready(port: int, timeout: float = 30.0) -> None:
    """Open the app only after Streamlit's health endpoint is available."""
    app_url = f"http://127.0.0.1:{port}"
    health_url = f"{app_url}{HEALTH_PATH}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # The URL is constructed locally and always uses loopback HTTP.
            with urllib.request.urlopen(health_url, timeout=1) as response:  # nosec B310
                if response.status == 200:
                    webbrowser.open(app_url)
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)


def main() -> None:
    """Launch the bundled Streamlit application."""
    from streamlit.web import cli as stcli

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    port = server_port()
    if os.environ.get("WIFI_SITE_SURVEY_OPEN_BROWSER", "true").lower() not in {
        "0",
        "false",
        "no",
    }:
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    sys.argv = [
        "streamlit",
        "run",
        str(bundled_app_path()),
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--browser.serverAddress=127.0.0.1",
        f"--browser.serverPort={port}",
    ]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()
