# macOS Wi-Fi Mapper

An interactive Wi-Fi site-survey tool for macOS. Upload a floor plan, click where
you are standing, and the app scans every visible access point through Apple's
native CoreWLAN framework. Measurements can be filtered, visualized, removed,
and exported as CSV.

## RSSI heatmaps

Every scan records SSID, BSSID, Wi-Fi band (2.4, 5, or 6 GHz), channel, and RSSI for each visible
access point. The map always shows the measured coordinates as blue diamond markers; hover a
marker to see every reading captured there.

Before scanning, calibrate the proportional floor plan by clicking the endpoints of a known
straight-line distance and entering its length in metres. A specific `(SSID, BSSID, band)`
combination becomes heatmap-eligible after it has been observed at five two-dimensionally spread
points, each at least one metre apart. SSID, BSSID, and band filters operate independently; leave
one empty to include all of its values. When several eligible combinations match, the map shows
the strongest interpolated RSSI at each location. Missing results remain unknown rather than
being treated as weak signals.

Interpolation is limited to the surveyed area. It visualizes the samples you collected; it does
not model walls, building materials, interference, or predict RF propagation in unsurveyed rooms.

## Install from a release

Download the archive for your Mac from the latest GitHub release:

- `wifi-site-survey-macos-arm64.zip` for Apple Silicon
- `wifi-site-survey-macos-x86_64.zip` for Intel

Then extract and run it:

```bash
xattr -dr com.apple.quarantine "WiFi Site Survey.app"
open "WiFi Site Survey.app"
```

The app bundle starts a local Streamlit server and opens the survey in your browser. It is ad-hoc
signed rather than notarized with a paid Apple Developer certificate. On first launch, macOS may
block it because it was downloaded from the internet. Open **System Settings → Privacy & Security**,
find the blocked WiFi Site Survey message, choose **Open Anyway**, and confirm. Alternatively,
Control-click the app in Finder and choose **Open**.

### Required Location Services permission

macOS considers SSIDs and BSSIDs to be location information. Without Location Services access,
CoreWLAN still reports RSSI and channel but replaces every SSID and BSSID with redacted values. Do
not use `sudo`; administrator privileges do not bypass this privacy control.

For the downloaded app:

1. Launch **WiFi Site Survey.app** and expand **Required: Location Services access for SSID and
   BSSID**.
2. Choose **Request Location Access** and approve the macOS dialog.
3. If permission was previously denied, open **System Settings → Privacy & Security → Location
   Services** and enable **WiFi Site Survey** manually.
4. Quit WiFi Site Survey completely, reopen it, and scan again.

These releases are ad-hoc signed, so macOS may treat an updated build as a new privacy identity and
retain a stale Location Services decision. If a previously working update starts returning redacted
SSID/BSSID values, quit it and reset only this app's Location authorization before reopening it:

```bash
tccutil reset Location com.steffenschumacher.wifisitesurvey
```

For source installations, enable Location Services for the application that starts Streamlit—such
as Terminal, iTerm, VS Code, or your IDE—then quit and reopen that application. A scan is rejected
instead of storing useless data when authorization is absent or macOS redacts every SSID/BSSID.

## Run from source

Python 3.10 or newer and [uv](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync --all-extras --locked
uv run streamlit run wifi_site_survey.py
```

Live scanning only works on macOS. The UI and automated tests can run on other
platforms, where scan attempts return a clear error.

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

Push a semantic-version tag to build ad-hoc-signed app bundles for both macOS architectures and
publish a GitHub release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The release workflow builds a self-contained app bundle per architecture, packages it while
preserving macOS symlinks and permissions, and publishes SHA-256 checksums.

The downloadable builds are ad-hoc signed rather than Apple-notarized, so macOS may quarantine an
app downloaded through a browser. After extracting it, clear that attribute before the first
launch:

```bash
xattr -dr com.apple.quarantine "/path/to/WiFi Site Survey.app"
open "/path/to/WiFi Site Survey.app"
```

## Data and privacy

Survey data stays in the Streamlit session until downloaded as CSV. The app does
not upload floor plans or Wi-Fi measurements anywhere.
