"""Launcher used by PyInstaller release binaries."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None  # type: ignore[assignment]

DEFAULT_PORT = 8501
HEALTH_PATH = "/_stcore/health"
INSTANCE_LOCK_PATH = Path(tempfile.gettempdir()) / "wifi-site-survey.lock"
_instance_lock: IO[str] | None = None


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


def claim_single_instance() -> tuple[IO[str] | None, int | None]:
    """Claim the application lock or return the existing instance's port."""
    lock_file = INSTANCE_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write("\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - every supported CPython platform has one implementation
            raise RuntimeError("No file-locking implementation is available")
    except (BlockingIOError, OSError):
        lock_file.seek(1 if msvcrt is not None else 0)
        value = lock_file.read().strip()
        lock_file.close()
        return None, int(value) if value.isdigit() else DEFAULT_PORT
    return lock_file, None


def record_instance_port(lock_file: IO[str], port: int) -> None:
    """Publish the server port while retaining the process-owned file lock."""
    lock_file.seek(1 if msvcrt is not None else 0)
    lock_file.truncate()
    lock_file.write(str(port))
    lock_file.flush()


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
    global _instance_lock

    lock_file, existing_port = claim_single_instance()
    if lock_file is None:
        webbrowser.open(f"http://127.0.0.1:{existing_port}")
        return
    _instance_lock = lock_file

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    port = server_port()
    record_instance_port(lock_file, port)
    from streamlit.web import cli as stcli

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
