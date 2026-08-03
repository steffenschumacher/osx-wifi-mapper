# Goal: Add Windows 11 Support to the Native PySide6 Application

Extend WiFi Site Survey so the browser-free PySide6 application works as a first-class Windows 11
desktop application while preserving the existing macOS support for both Apple Silicon (`arm64`)
and Intel (`x86_64`). Windows must provide the same survey workflow and data quality as macOS:
nearby Wi-Fi scans containing SSID, BSSID, RSSI, channel, and derived 2.4/5/6 GHz band; calibrated
floor plans; sample markers; independently optional filters; heatmaps; and version-1 `.wifisurvey`
save/load compatibility.

Implement this on the `feature/windows-support` branch. Do not remove or regress either macOS
architecture. Keep platform-specific scanning and packaging behind clear boundaries, and retain one
shared PySide6 UI and survey model wherever possible.

## Required investigation before implementation

1. Inspect the current native architecture, CoreWLAN scanner, packaging specifications, CI,
   release workflow, tests, README, and `AGENTS.md`.
2. Use current primary Microsoft documentation to verify Windows 11 Native Wi-Fi API behavior,
   especially Windows 11 24H2 precise-location consent and `ERROR_ACCESS_DENIED` handling.
3. Prefer the supported Win32 Native Wi-Fi API in `wlanapi.dll`:
   - `WlanOpenHandle` and `WlanCloseHandle`
   - `WlanEnumInterfaces`
   - `WlanScan`
   - scan completion notification or a carefully bounded fallback wait
   - `WlanGetNetworkBssList`
   - `WlanFreeMemory`
4. Determine through a tested prototype which `WLAN_BSS_ENTRY` fields reliably expose SSID,
   BSSID, RSSI, center frequency, PHY type, and channel on Windows 11.
5. Never parse human-readable output from `netsh wlan` as the production scanning implementation.
   It may be useful only as a diagnostic comparison.

## Cross-platform scanner architecture

- Define a small scanner interface/protocol with a platform-neutral reading schema.
- Move the existing CoreWLAN behavior into a clearly named macOS implementation without changing
  its bundle identity or Location Services behavior.
- Add a Windows scanner that calls `wlanapi.dll`, preferably through well-contained `ctypes`
  definitions. If a compiled helper is materially safer, document and justify that choice and make
  its build reproducible.
- Select the scanner through `sys.platform`; unsupported platforms must retain a clear diagnostic
  rather than failing at import time.
- Native library imports must be lazy or guarded so tests and UI construction work on Linux CI.
- Ensure every native handle and allocated WLAN buffer is released on success, failure, timeout,
  and cancellation paths.
- Support multiple enabled Wi-Fi adapters. De-duplicate identical observations conservatively,
  preferring the strongest RSSI when the same `(SSID, BSSID, band, channel)` is reported more than
  once.
- Trigger a fresh scan and wait asynchronously so the Qt event loop remains responsive. Prevent
  overlapping scans and retain the existing full-window scanning banner.

## Windows reading normalization

Each Windows observation must use the existing application schema:

- `ssid`: decode the length-delimited DOT11 SSID safely; preserve hidden SSIDs as `<hidden>`.
- `bssid`: uppercase, colon-separated six-byte MAC address.
- `rssi_dbm`: integer dBm from `lRssi`, constrained or validated consistently with the model.
- `channel`: derive from `ulChCenterFrequency` using well-tested 2.4, 5, and 6 GHz mappings.
- `band`: derive as `2.4 GHz`, `5 GHz`, or `6 GHz`; do not infer band merely from SSID or PHY.
- Reject malformed native structures without crashing the full scan.

Add unit tests for channel/frequency boundaries and representative channels in every band. Include
fixtures or synthetic native structures for parsing tests without requiring Wi-Fi hardware in CI.

## Windows privacy, permissions, and diagnostics

Modern Windows 11 restricts BSSID-bearing Wi-Fi APIs using precise-location consent. Design this as
an explicit application flow, not as a mysterious scan failure:

- A scan must run as the signed-in desktop user; never request administrator elevation and never
  recommend running the app as Administrator.
- Detect `ERROR_ACCESS_DENIED` and explain that **Location services** and **Let desktop apps access
  your location** must both be enabled under **Settings → Privacy & security → Location**.
- Where supported, initiate the one-time Windows consent prompt at a user-initiated moment before
  scanning. Evaluate `WiFiAdapter.RequestAccessAsync`/`wiFiControl` and precise-location access for
  packaged and unpackaged desktop applications, using Microsoft-supported behavior rather than
  assumptions.
- Provide an in-app button that opens `ms-settings:privacy-location` when access is denied.
- Distinguish permission denial from: no Wi-Fi adapter, disabled radio, stopped WLAN AutoConfig
  service, scan timeout, and an empty scan result.
- Avoid logging or displaying credentials, saved Wi-Fi profile secrets, or unrelated personal
  location information.
- Document that Windows may list access under desktop applications rather than offering a separate
  per-application toggle, depending on installation/package identity and Windows version.

## PySide6 user experience

- Use the current shared PySide6 Widgets application. Do not add a browser, local server,
  QtWebEngine, or a second Windows-only UI.
- Preserve the two-stage floor-plan/calibration workflow, panning, crosshair sampling, adaptive
  marker contrast, scale ruler, filters, heatmap behavior, and scan-completion guidance.
- Use native-looking Windows file dialogs and menu shortcuts while preserving macOS behavior.
- Ensure Windows display scaling at 100%, 125%, 150%, and 200% does not blur the floor plan or
  misplace clicks. Coordinate conversion must remain independent of device pixels.
- Ensure window close, Alt+F4, and Task Manager termination behave normally, and scan workers do not
  prevent graceful application exit.

## Survey compatibility

- Keep `.wifisurvey` format version 1 compatible in both directions.
- A survey captured on macOS must open on Windows and vice versa without rewriting its image,
  calibration, points, or readings.
- Preserve the current maximum/strongest-RSSI combination strategy and five-point, one-metre-spread
  eligibility rule.
- Add a cross-platform round-trip test with Unicode SSIDs, hidden SSIDs, 2.4/5/6 GHz readings, and
  Windows-style BSSIDs.

## Windows packaging

- Add a deterministic PyInstaller Windows build producing a GUI application named
  `WiFi Site Survey.exe` without a console window for normal use.
- Keep a documented diagnostic mode or companion command that exposes useful logs when users need
  help troubleshooting scans.
- Include the license, third-party notices, Qt libraries/plugins, and required Visual C++ runtime
  handling. Do not bundle credentials or a PAT.
- Prefer a normal onedir ZIP for the first Windows release because it is easier to audit and debug.
  If an installer is added, use a reproducible, well-maintained tool and support clean uninstall.
- Code signing is optional until a Windows certificate is available, but clearly document
  SmartScreen warnings and safe verification through published SHA-256 checksums. Do not weaken
  SmartScreen or advise users to disable antivirus.
- Target Windows 11 `x86_64` first. Evaluate Windows on ARM explicitly; do not label an artifact
  ARM64 unless it is built and tested natively for that architecture.

## CI and release automation

- Keep existing macOS `arm64` and `x86_64` build-and-smoke-test jobs unchanged in coverage.
- Add Windows CI on a supported GitHub-hosted Windows runner that:
  1. installs the locked dependencies with `uv`;
  2. runs tests, Ruff, Bandit, and secret scanning where applicable;
  3. builds the exact Windows artifact;
  4. extracts and starts that artifact in a bounded smoke test;
  5. confirms the process remains alive and then terminates cleanly;
  6. verifies expected executable metadata and that no browser/server port is opened.
- Hardware Wi-Fi scans cannot be trusted on hosted CI. Keep API parsing and error paths fully
  testable with fakes, and define a short manual Windows 11 hardware acceptance checklist.
- Extend tag releases without changing existing macOS asset names. Add a clearly named Windows
  archive and SHA-256 file, for example:
  - `wifi-site-survey-windows-x86_64.zip`
  - `wifi-site-survey-windows-x86_64.zip.sha256`
- Smoke-test the exact archive later uploaded to GitHub, not merely the build directory.
- Do not tag or publish a new public version until Windows hardware scanning has been manually
  verified by the user and all automated checks pass.

## Beginner-friendly Windows documentation

Add a self-contained Windows 11 guide near the beginning of `README.md` and, if it improves
clarity, a more detailed `docs/windows.md`. Assume the reader has never used PowerShell, Python,
Git, or `uv`. It must cover both paths below.

### Running a GitHub release

1. How to determine whether the machine is x64 or ARM64 in **Settings → System → About → System
   type**.
2. Exactly which release archive to download.
3. How to verify its SHA-256 checksum in PowerShell with `Get-FileHash`.
4. How to extract the ZIP through File Explorer and why the executable must remain with its bundled
   files.
5. How to handle an unsigned-app SmartScreen dialog safely using **More info → Run anyway**, while
   checking that the publisher/signature limitation and checksum match the project documentation.
6. How to enable Location services and desktop-app location access.
7. How to launch, grant access, load/calibrate a floor plan, and make the first scan.
8. Troubleshooting for access denied, no adapter, disabled Wi-Fi, WLAN AutoConfig, empty results,
   SmartScreen, antivirus quarantine, and collecting diagnostic output.
9. How to close and remove the portable application.

### Running from source

Provide literal, copy/paste-ready PowerShell commands and explain where to type them:

1. Install Git for Windows and `uv` using their official instructions.
2. Open **PowerShell** as a normal user, not Administrator.
3. Clone the repository, change into its directory, and switch to the Windows feature branch while
   it is under development.
4. Run `uv sync --all-extras --locked`.
5. Launch the PySide6 application with the project entry point.
6. Explain the first dependency download, Windows Firewall expectations (the app opens no server),
   Location settings, updates with `git pull`, and how to stop/close the app.
7. Include diagnostic commands such as `Get-NetAdapter`, `Get-Service WlanSvc`, and a safe way to
   capture application logs without exposing saved Wi-Fi credentials.

Keep all commands valid in current Windows PowerShell 5.1 and PowerShell 7 where practical. Clearly
label commands that differ. Do not tell users to use `sudo`, Homebrew, macOS paths, Bash syntax, or
administrator elevation unless a particular installation action genuinely requires it.

## Repository guidance

- Update `AGENTS.md` so it accurately describes the native cross-platform PySide6 architecture,
  platform-specific scanners, Windows packaging, and the macOS identity constraints that still
  apply.
- Keep `uv.lock` synchronized with `pyproject.toml`.
- Preserve branch protection, restricted Actions policy, secret scanning, and read-only default
  workflow permissions.
- Do not commit generated build artifacts, debug logs, Wi-Fi scans, floor plans, credentials, or
  the GitHub PAT.

## Testing and completion criteria

Before presenting a Windows beta:

1. Run the complete existing test suite and all pre-commit hooks on Linux.
2. Run the complete supported test suite on Windows 11.
3. Build and smoke-test the Windows x86-64 artifact in CI.
4. Re-run both macOS native packaging jobs to prevent regressions.
5. Manually test on real Windows 11 Wi-Fi hardware:
   - permission prompt and denial/recovery;
   - at least one visible SSID and BSSID;
   - plausible RSSI and correct channel/band;
   - repeated scans at multiple floor-plan points;
   - save, quit, reopen, and continue the survey;
   - a `.wifisurvey` exchanged with macOS;
   - graceful close during and after scanning.

The goal is complete only when the shared PySide6 application runs on Windows 11 and both existing
macOS architectures, automated checks and exact-artifact smoke tests pass, Windows setup and
troubleshooting are documented for a novice, and real Windows hardware validation has either
passed or is explicitly reported as the sole remaining release blocker. Do not claim hardware
behavior was tested when no physical Windows Wi-Fi machine was available.
