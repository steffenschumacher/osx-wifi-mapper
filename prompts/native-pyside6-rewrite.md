# Goal: Build a Native PySide6 Wi-Fi Site Survey Application

Create a production-quality, browser-free PySide6 version of macOS Wi-Fi Mapper on a separate
`native-pyside6` branch. Preserve the existing Streamlit implementation and release line while the
native version is developed and validated.

## Outcome

Deliver a responsive native macOS application with feature parity with the current survey tool:

- Load PNG/JPG floor plans without distorting their aspect ratio.
- Calibrate map distance by selecting two endpoints and entering the real distance in metres.
- Capture CoreWLAN scans at map coordinates while enforcing one-metre sample spacing.
- Retain SSID, BSSID, band, channel, RSSI, timestamp, and point metadata.
- Display persistent, numbered sample markers with hover or click details.
- Render filterable red–yellow–green RSSI heatmaps.
- Filter SSID, BSSID, and band independently, treating an empty filter as all values.
- Require five two-dimensionally spread, one-metre-separated samples for each eligible
  `(SSID, BSSID, band)` triple.
- Interpolate triples independently and combine overlapping results using strongest RSSI.
- Save and restore the complete survey—including original image, calibration, points, and
  measurements—in the versioned `.wifisurvey` format.
- Export measurements as CSV.
- Request and explain macOS Location Services authorization for SSID/BSSID access.
- Start, remain responsive, and quit as a normal native macOS application without a browser or
  local web server.

## Branch and compatibility

- Create and work only on a separate `native-pyside6` branch.
- Do not remove or regress the Streamlit implementation on `main`.
- Extract reusable domain logic into UI-independent modules where practical rather than
  duplicating it.
- Preserve compatibility with `.wifisurvey` format version 1 produced by v0.2.7.
- Keep the bundle identifier `com.steffenschumacher.wifisitesurvey` stable.
- Continue using `uv`, the committed lock file, and Python 3.10 or newer.

## Native architecture

- Use PySide6 Widgets rather than QtWebEngine or an embedded browser.
- Implement the floor plan with `QGraphicsView`/`QGraphicsScene` or an equivalently appropriate
  native graphics architecture.
- Keep the floor-plan pixmap resident. Update markers and heatmap overlays independently; do not
  reconstruct the whole UI for each click.
- Use explicit scene/image coordinate transforms so scaling, calibration, marker placement, and
  heatmap pixels remain consistent at every zoom level and window size.
- Support zooming and panning without modifying stored survey coordinates.
- Render the heatmap into a transparent `QImage`/pixmap layer below markers and above the floor
  plan.
- Run CoreWLAN scanning outside the GUI thread using Qt signals and a worker/thread-pool pattern.
- Disable conflicting scan actions while a scan is active and surface success or actionable
  errors in the window.
- Use native dialogs for opening images/surveys, saving surveys, and exporting CSV.
- Implement normal window close, application Quit, and cleanup behavior.

## Domain separation

Organize reusable code into testable modules for at least:

- Survey data model and schema validation.
- `.wifisurvey` serialization/deserialization.
- CoreWLAN and Core Location integration.
- Calibration and coordinate conversion.
- Triple eligibility and independent filtering.
- RSSI interpolation and strongest-surface composition.
- CSV export.

The UI layer should orchestrate these services without importing Streamlit or Plotly.

## Packaging and licensing

- Add PySide6 using a compatible, bounded dependency range and update `uv.lock`.
- Use dynamically linked Qt frameworks and include the notices needed for LGPLv3 compliance;
  do not use Qt modules that require GPL-only licensing for this application.
- Prefer an onedir/standalone macOS app bundle. Do not introduce a onefile/windowed bundle.
- Initially reuse the proven PyInstaller dual-architecture workflow unless a tested
  `pyside6-deploy`/Nuitka setup is demonstrably more reliable.
- Build both Intel `x86_64` and Apple Silicon `arm64` artifacts.
- Preserve the final-archive extraction, deep-signature, launch, and process-lifecycle smoke tests.
- Do not publish a native release tag until feature parity and packaged-app acceptance criteria
  pass.

## Testing

- Keep all existing domain tests passing where the underlying behavior is shared.
- Add Qt tests (prefer `pytest-qt`) for:
  - Main-window construction and clean close.
  - Floor-plan aspect ratio and coordinate transforms.
  - Two-point calibration workflow.
  - Marker creation, visibility, numbering, and details.
  - Independent SSID/BSSID/band filters.
  - Heatmap layer creation and refresh.
  - Async scan success, failure, and UI re-enablement.
  - Save/load round-trip compatibility with v1 `.wifisurvey` files.
- Add or retain tests for five-point eligibility, one-metre spacing, interpolation, strongest RSSI,
  malformed survey rejection, and legacy rows.
- Keep Ruff, Bandit, detect-secrets, Gitleaks, and pre-commit checks passing.
- Add a native packaged-app smoke test that verifies launch, a responsive process, and graceful
  termination without requiring a browser or port.

## Documentation

- Document native development and launch commands.
- Document macOS Location Services behavior and the limitation of ad-hoc signatures across
  updates.
- Document `.wifisurvey` compatibility between Streamlit v0.2.7 and the native application.
- Document Qt/PySide6 LGPL obligations and included notices.
- Keep the existing Streamlit instructions clearly available while both versions coexist.

## Acceptance criteria

1. Work exists on `native-pyside6`, with `main` left intact except for this prompt if necessary.
2. The application starts as a native window and never starts Streamlit, a browser, or a TCP
   server.
3. The UI remains responsive during scans and heatmap updates.
4. Floor plans retain their aspect ratio at all supported window sizes.
5. Calibration, five-point/one-metre eligibility, independent filters, strongest-RSSI heatmaps,
   numbered markers, point deletion, and CSV export match existing behavior.
6. A `.wifisurvey` file from v0.2.7 loads correctly, and a native-saved file round-trips without
   losing image, scale, endpoints, points, or readings.
7. Normal close and Quit terminate the app promptly; no orphan process remains.
8. Intel and Apple Silicon final archives pass signature, launch, responsiveness, and graceful
   shutdown smoke tests.
9. Automated tests and security checks pass with no secrets, generated build output, or unrelated
   changes committed.
