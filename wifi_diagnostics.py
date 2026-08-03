"""Privacy-conscious console diagnostics for native Wi-Fi scanning."""

from __future__ import annotations

import platform
import sys
from collections import Counter

from wifi_scanner import scan_wifi


def main() -> int:
    print("WiFi Site Survey diagnostics")
    print(f"Operating system: {platform.platform()}")
    print(f"Python: {platform.python_version()}")
    print("This check does not display SSIDs, BSSIDs, or saved Wi-Fi credentials.")
    try:
        readings = scan_wifi()
    except Exception as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        return 1
    bands = Counter(str(reading.get("band", "Unknown")) for reading in readings)
    identified = sum(
        reading.get("ssid") != "<hidden>" and reading.get("bssid") != "<unavailable>"
        for reading in readings
    )
    print(f"Scan succeeded: {len(readings)} access-point observations")
    print(f"Readings with both SSID and BSSID: {identified}")
    print(
        "Bands: "
        + (", ".join(f"{band}={count}" for band, count in sorted(bands.items())) or "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
