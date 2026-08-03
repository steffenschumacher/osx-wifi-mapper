# WiFi Site Survey

A native Wi-Fi site-survey tool for macOS and Windows 11. Upload a floor plan, click where you are
standing, and the app scans visible access points through Apple's CoreWLAN or the Windows Native
Wi-Fi API. Measurements can be filtered, visualized, removed, saved, and exported as CSV.

> **Transparency note:** This project is fully vibe-coded. Its design, implementation, tests, and
> release automation were developed through iterative collaboration with AI coding agents and
> validated with automated and hands-on testing.

## RSSI heatmaps

Every scan records SSID, BSSID, Wi-Fi band (2.4, 5, or 6 GHz), channel, and RSSI for each visible
access point. The map shows measured coordinates using markers whose color is selected to contrast
with the uploaded floor plan; hover a marker to see every reading captured there.

Before scanning, calibrate the proportional floor plan by clicking the endpoints of a known
straight-line distance and entering its length in metres. A specific `(SSID, BSSID, band)`
combination becomes heatmap-eligible after it has been observed at five two-dimensionally spread
points, each at least one metre apart. SSID, BSSID, and band filters operate independently; leave
one empty to include all of its values. When several eligible combinations match, the map shows
the strongest interpolated RSSI at each location. Missing results remain unknown rather than
being treated as weak signals.

Interpolation is limited to the surveyed area. It visualizes the samples you collected; it does
not model walls, building materials, interference, or predict RF propagation in unsurveyed rooms.

Use **Save complete survey** to download one `.wifisurvey` file containing the original floor-plan
image, calibration endpoints and metre scale, measurement points, and every captured Wi-Fi reading.
Choose **Open saved survey** after starting the app to restore that file and continue surveying.
The map displays each captured location as a contrasting point; hover it to reveal its number and
inspect its readings.

## Install from a release

### Windows 11

Windows support is currently available on the `feature/windows-support` development branch and is
awaiting physical Windows Wi-Fi hardware validation before its first tagged release. See the
[complete Windows 11 guide](docs/windows.md) for novice-friendly source setup, future release
installation, checksum verification, Location permission, SmartScreen, and troubleshooting steps.
Use the separate [Windows hardware validation checklist](docs/windows-hardware-validation.md) when
testing the beta on a physical laptop.

### macOS

Download the archive for your Mac from the latest GitHub release:

- `wifi-site-survey-macos-arm64.zip` for Apple Silicon
- `wifi-site-survey-macos-x86_64.zip` for Intel

Then extract and run it:

```bash
xattr -dr com.apple.quarantine "WiFi Site Survey.app"
open "WiFi Site Survey.app"
```

The app is a native Qt application: it does not open a browser or start a local server. It is
ad-hoc signed rather than notarized with a paid Apple Developer certificate. On first launch,
macOS may block it because it was downloaded from the internet. Open **System Settings → Privacy &
Security**, find the blocked WiFi Site Survey message, choose **Open Anyway**, and confirm.
Alternatively, Control-click the app in Finder and choose **Open**.

### Required Location Services permission

macOS considers SSIDs and BSSIDs to be location information. Without Location Services access,
CoreWLAN still reports RSSI and channel but replaces every SSID and BSSID with redacted values. Do
not use `sudo`; administrator privileges do not bypass this privacy control.

For the downloaded app:

1. Launch **WiFi Site Survey.app**.
2. Choose **Request Location Access** in the controls and approve the macOS dialog.
3. If permission was previously denied, open **System Settings → Privacy & Security → Location
   Services** and enable **WiFi Site Survey** manually.
4. Quit WiFi Site Survey completely, reopen it, and scan again.

These releases are ad-hoc signed, so macOS may treat an updated build as a new privacy identity and
retain a stale Location Services decision. If a previously working update starts returning redacted
SSID/BSSID values, quit it and reset only this app's Location authorization before reopening it:

```bash
tccutil reset Location com.steffenschumacher.wifisitesurvey
```

For source installations, enable Location Services for the application that starts Python—such as
Terminal, iTerm, VS Code, or your IDE—then quit and reopen that application. A scan is rejected
instead of storing useless data when authorization is absent or macOS redacts every SSID/BSSID.

## Run from source

Python 3.10 or newer and [uv](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync --all-extras --locked
uv run wifi-site-survey-native
```

Live scanning works on macOS and Windows 11. The UI and automated tests can run on Linux, where scan
attempts return a clear unsupported-platform error.

The browser-free Qt Widgets implementation keeps the floor
plan and overlay layers resident, performs native scans in a worker thread, and reads the same
version-1 `.wifisurvey` files as the Streamlit application.

The native workflow has two stages. Opening a floor plan first presents a mandatory calibration
dialog: select two endpoints of a known distance and enter its length in metres. Cancelling this
initial dialog unloads the image, because sampling is unavailable until setup is complete. Once
calibrated, the compact **Recalibrate…** action reopens the dialog without changing the active
survey unless the new calibration is accepted.

Use the **View** menu to zoom or reset the view. Once zoomed in, drag the floor plan with a mouse,
trackpad, or macOS three-finger drag; dragging pans without creating a sample. A stationary click
uses the crosshair location for the next Wi-Fi scan.

The previous Streamlit frontend remains available from source with
`uv run streamlit run wifi_site_survey.py` for compatibility.

PySide6 is distributed under LGPLv3/GPLv3 or commercial terms. This project uses dynamically
linked Qt libraries under LGPLv3. The native bundle includes `THIRD_PARTY_NOTICES.md` and the GPLv3
and LGPLv3 texts under `LICENSES`; users may replace the bundled compatible Qt dynamic libraries.

On first use, choose **Request Location Access** and approve WiFi Site Survey in System Settings →
Privacy & Security → Location Services. SSID and BSSID values remain redacted without that grant.
Ad-hoc signatures have no durable Apple identity, so installing a newly built app may require
granting Location Services again.

Native and Streamlit versions read and write the same version-1 `.wifisurvey` files. Those archives
contain the original floor plan, calibration endpoints and scale, sample points, and Wi-Fi readings.

## Development

```bash
uv sync --all-extras --locked
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest
```

The hooks run Ruff formatting/linting, Bandit security checks, and Yelp's
`detect-secrets` password/credential scanner. CI repeats these checks and also
runs a dedicated Gitleaks scan. Dependencies are reproducible through the
committed `uv.lock`; standard `pip install .` remains supported.

## Releasing

After physical Windows validation, push a semantic-version tag to build Windows x86-64 plus
ad-hoc-signed macOS app bundles for both macOS architectures and publish a GitHub release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The release workflow builds self-contained native artifacts, tests the exact archives, preserves
macOS symlinks and permissions, and publishes SHA-256 checksums.

The downloadable builds are ad-hoc signed rather than Apple-notarized, so macOS may quarantine an
app downloaded through a browser. After extracting it, clear that attribute before the first
launch:

```bash
xattr -dr com.apple.quarantine "/path/to/WiFi Site Survey.app"
open "/path/to/WiFi Site Survey.app"
```

## Data and privacy

Survey data stays local. It remains in memory unless exported as CSV or saved as a `.wifisurvey`
archive; neither frontend uploads floor plans or Wi-Fi measurements anywhere.
