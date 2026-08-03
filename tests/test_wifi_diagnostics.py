from __future__ import annotations

import wifi_diagnostics


def test_diagnostics_summarizes_without_identifiers(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        wifi_diagnostics,
        "scan_wifi",
        lambda: [
            {"ssid": "PrivateName", "bssid": "AA:BB:CC:DD:EE:FF", "band": "5 GHz"},
            {"ssid": "<hidden>", "bssid": "11:22:33:44:55:66", "band": "2.4 GHz"},
        ],
    )
    assert wifi_diagnostics.main() == 0
    output = capsys.readouterr().out
    assert "Scan succeeded: 2" in output
    assert "2.4 GHz=1" in output
    assert "5 GHz=1" in output
    assert "PrivateName" not in output
    assert "AA:BB" not in output


def test_diagnostics_returns_failure(monkeypatch, capsys) -> None:
    def fail():
        raise RuntimeError("location permission denied")

    monkeypatch.setattr(wifi_diagnostics, "scan_wifi", fail)
    assert wifi_diagnostics.main() == 1
    assert "location permission denied" in capsys.readouterr().err
