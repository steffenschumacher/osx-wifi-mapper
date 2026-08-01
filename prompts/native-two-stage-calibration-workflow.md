# Goal: Native Two-Stage Floor-Plan Calibration Workflow

Implement a compact, mandatory calibration workflow in the browser-free PySide6 application on
the `native-pyside6` development branch, while preserving `.wifisurvey` compatibility and the
existing Streamlit application.

## Desired workflow

The native application must have two clearly separated stages:

1. **Floor plan and calibration:** the user loads an image and completes two-point real-distance
   calibration in a modal popup dialog.
2. **Wi-Fi sampling:** the main survey workspace becomes available only after calibration succeeds.

## Requirements

- Remove the permanently expanded distance-calibration group from the controls dock.
- Replace it with a compact calibration status and an action such as **Recalibrate…** that opens a
  modal calibration dialog.
- Opening a new floor-plan image must immediately and automatically open the calibration dialog.
- The calibration dialog must display the floor plan at its correct aspect ratio and allow the user
  to select two visibly marked endpoints joined by a visible line.
- The dialog must accept the real reference distance in metres and clearly show the calculated
  metres-per-coordinate-unit scale before completion.
- The dialog may only accept when it has two distinct endpoints and a valid positive distance.
- If the user cancels initial calibration after loading a new image, unload that image and return to
  the empty state. The user must load an image and complete calibration before sampling is possible.
- Recalibration of an existing active survey must be cancellable without losing the existing image,
  calibration, points, or measurements.
- Successful recalibration must update the document endpoints and scale and refresh eligibility,
  filters, overlays, and markers without losing samples.
- Loading a valid `.wifisurvey` file that already contains a valid calibration may enter the
  sampling stage directly. A survey without valid calibration must require the modal calibration
  stage; cancelling it must leave no active survey loaded.
- Disable or hide sampling actions whenever no fully calibrated document is active.
- Preserve continuous width-normalized coordinates, image aspect ratio, five-point eligibility,
  one-metre spacing, asynchronous scanning, heatmaps, save/load, CSV export, and version-1 survey
  compatibility.
- Keep the calibration UI responsive and native; do not introduce Streamlit, Plotly, a browser, or
  a local server.

## Testing and acceptance

- Add Qt tests for forced calibration after image loading, visible endpoints and line, successful
  acceptance, initial cancellation unloading the image, safe cancellation during recalibration,
  direct loading of calibrated surveys, mandatory calibration for uncalibrated surveys, and blocked
  sampling before setup completion.
- Keep all existing tests passing.
- Run Ruff formatting/linting, Bandit, detect-secrets, pre-commit, and the complete pytest suite.
- Push the completed implementation to `origin/native-pyside6` only after local verification.
- Confirm the native GitHub CI workflow, including Intel and Apple Silicon extracted-archive smoke
  tests, succeeds before marking the goal complete.
