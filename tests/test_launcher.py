from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import wifi_site_survey_launcher as launcher


def test_source_app_path_exists() -> None:
    path = launcher.bundled_app_path()
    assert path == Path(launcher.__file__).resolve().parent / "wifi_site_survey.py"
    assert path.is_file()


def test_server_port_uses_configured_available_port(monkeypatch) -> None:
    probe = MagicMock()
    probe.__enter__.return_value = probe
    monkeypatch.setenv("WIFI_SITE_SURVEY_PORT", "18765")
    monkeypatch.setattr(launcher.socket, "socket", MagicMock(return_value=probe))

    assert launcher.server_port() == 18765
    probe.bind.assert_called_once_with(("127.0.0.1", 18765))


def test_browser_opens_only_after_server_is_healthy(monkeypatch) -> None:
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    urlopen = MagicMock(return_value=response)
    browser_open = MagicMock()
    monkeypatch.setattr(launcher.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(launcher.webbrowser, "open", browser_open)

    launcher.open_browser_when_ready(8501, timeout=0.1)

    urlopen.assert_called_once_with("http://127.0.0.1:8501/_stcore/health", timeout=1)
    browser_open.assert_called_once_with("http://127.0.0.1:8501")


def test_main_forces_production_mode_and_matching_ports(monkeypatch) -> None:
    streamlit_cli = MagicMock()
    streamlit_cli.main.return_value = 0
    monkeypatch.setattr(launcher, "server_port", lambda: 18765)
    monkeypatch.setenv("WIFI_SITE_SURVEY_OPEN_BROWSER", "false")
    monkeypatch.setattr("streamlit.web.cli.main", streamlit_cli.main)

    try:
        launcher.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert "--global.developmentMode=false" in launcher.sys.argv
    assert "--server.headless=true" in launcher.sys.argv
    assert "--server.address=127.0.0.1" in launcher.sys.argv
    assert "--server.port=18765" in launcher.sys.argv
    assert "--browser.serverPort=18765" in launcher.sys.argv
