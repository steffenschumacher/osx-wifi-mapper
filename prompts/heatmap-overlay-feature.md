# Goal: Add Filterable Wi-Fi RSSI Heatmap Overlays

Implement a production-quality heatmap overlay for the existing macOS Wi-Fi site-survey
application in this repository. Work autonomously until the complete feature is implemented,
tested, documented, and verified. Preserve all existing survey, filtering, point-management,
CSV-export, packaging, and release behavior unless this specification explicitly changes it.

## Required outcome

After collecting enough spatial samples, a user can select one or more Wi-Fi identities and see
an interpolated RSSI heatmap over the uploaded floor-plan image. A Wi-Fi identity (called a
"triple" below) is:

```text
(SSID, BSSID, band)
```

Here, `band` means the Wi-Fi frequency band: 2.4 GHz, 5 GHz, or 6 GHz. Channel remains separate
measurement metadata and must continue to be captured and exported.

## 1. Capture and store Wi-Fi band

- Extend the CoreWLAN scanner to obtain the band from each network's `CWChannel`, using the
  native CoreWLAN channel-band value rather than inferring it only from the channel number.
- Normalize bands into stable, user-facing values: `2.4 GHz`, `5 GHz`, and `6 GHz`.
- Handle unknown or future CoreWLAN band values safely as `Unknown` without failing the scan.
- Store `band` on every measurement row alongside SSID, BSSID, RSSI, and channel.
- Include `band` in CSV exports.
- Preserve the lazy CoreWLAN loading and the application's useful non-macOS error behavior.

## 2. Triple eligibility

- Count samples by `(SSID, BSSID, band)` using **distinct measurement points/coordinates**, not
  raw DataFrame row count.
- A triple is heatmap-eligible only when it has at least **10 distinct sampled coordinates**.
- Also require sufficient two-dimensional spatial spread for interpolation. At minimum, reject
  coincident or effectively collinear point sets even if they contain 10 points.
- Ineligible triples must not be selectable for heatmap rendering.
- Clearly show ineligible observed triples and why they are unavailable, including progress such
  as `7/10 points` or `insufficient spatial spread`.
- Recompute eligibility immediately after a scan or point deletion.

## 3. Filters

- Provide filters derived from the unique sampled values for:
  - SSID
  - BSSID
  - band
- Filters should cascade where practical so irrelevant combinations are not presented.
- Only eligible triples may contribute to a heatmap.
- Make selection state predictable when new samples appear or points are deleted; do not
  silently enable an unintended triple.
- Provide a clear empty state when no triple is eligible or selected.

## 4. Interpolation and combination semantics

- Produce a smooth RSSI surface in the existing normalized image coordinate system (`0..100`
  on both axes).
- Interpolate each selected eligible `(SSID, BSSID, band)` triple independently from its own
  samples.
- Do not treat a missing AP in a scan as an artificial RSSI value such as `-100 dBm`; missing
  data remains unknown.
- Do not imply coverage arbitrarily far outside surveyed space. Mask interpolation outside the
  supported sampled region (for example, outside the triple's convex hull and/or beyond a
  justified maximum sample distance).
- If several eligible triples are selected, combine their interpolated surfaces pixel by pixel
  using the strongest RSSI:

  ```text
  combined_rssi(x, y) = max(rssi_for_each_selected_triple(x, y))
  ```

- Ignore unknown/masked cells when taking the maximum. A cell remains unknown when no selected
  triple has a supported interpolated value there.
- Choose a deterministic interpolation method suitable for sparse site-survey measurements.
  Inverse-distance weighting or another well-justified method is acceptable. Keep interpolation
  logic separate from Streamlit UI code and unit-test it directly.
- Keep computation responsive for normal residential surveys. Cache derived surfaces when useful,
  and invalidate them correctly after filter or measurement changes.

## 5. Heatmap presentation

- Render the surface as a semi-transparent overlay above the floor-plan image and below sample
  markers.
- Use a fixed, comparable RSSI color scale rather than auto-scaling each dataset:
  - strong signal: green
  - intermediate signal: yellow
  - weak signal: red
- Use sensible fixed dBm bounds and document them in the UI; preserve the existing threshold
  meaning where practical.
- Include a color bar labeled in dBm.
- Provide an opacity control or choose a tested opacity that keeps the floor plan readable.
- Preserve click-to-measure behavior across the usable map area.
- Filters must update the overlay dynamically without initiating a Wi-Fi scan.

## 6. Sample-point markers and hover details

- Display a distinct sample-point icon/marker above the heatmap for every measured coordinate,
  including points that do not yet make a triple eligible.
- Hovering a marker must show the coordinate and the readings captured at that point.
- Each reading should be displayed clearly as:

  ```text
  SSID / BSSID / band / channel: RSSI dBm
  ```

- Sort or otherwise structure long hover lists so they remain understandable.
- Make hidden SSIDs, unavailable BSSIDs, unknown bands, and missing channels render safely.
- Deleting a sample point must remove its readings, update marker hover data, recalculate triple
  eligibility, and update the heatmap.

## 7. Architecture and compatibility

- Keep the application straightforward to run with Streamlit and compatible with the existing
  PyInstaller single-binary release workflow.
- Prefer small, testable functions for band normalization, eligibility, interpolation, surface
  combination, filter derivation, and hover formatting.
- Update `pyproject.toml` and `uv.lock` if a numerical/interpolation dependency is required.
- Do not use Apple's deprecated `airport` command.
- Do not upload floor plans or measurements to an external service.

## 8. Testing requirements

Add or update automated tests covering at least:

- CoreWLAN band extraction and normalization for 2.4, 5, 6 GHz, and unknown values.
- CSV/data schema preservation of band and channel.
- Eligibility at 9 versus 10 distinct coordinates.
- Duplicate rows or duplicate coordinates not inflating eligibility.
- Rejection of collinear/degenerate samples.
- Filtering by SSID, BSSID, and band.
- Interpolation at known sample points and masking outside supported space.
- Pixel-wise `max` combination of multiple surfaces, including masked cells.
- Stable fixed RSSI-to-color mapping.
- Marker hover content containing all expected triples, channels, and RSSI readings.
- Correct recalculation after point deletion.
- Existing scanner, map interaction, export, and point-management tests continue to pass.

Maintain the repository's configured coverage threshold. Run the complete test, lint, formatting,
security, and secret-scanning suite rather than only the new tests.

## 9. Documentation and delivery

- Update the README with heatmap usage, the 10-point rule, filter semantics, strongest-signal
  combination behavior, and the limitations of interpolated RF visualization.
- Explain that interpolation does not model walls and is a visualization of collected samples,
  not a predictive RF simulation.
- Keep source-run and tagged binary-release instructions correct.
- Update any screenshots only if the repository already uses them; do not add generated imagery
  solely for decoration.

## Completion gates

Do not consider the goal complete until all of the following are true and verified from the
current worktree:

1. Real CoreWLAN scan results include a normalized band field in the data model.
2. Only triples with at least 10 distinct, spatially valid sample coordinates can render a
   heatmap.
3. Multiple selected triple surfaces combine using pixel-wise maximum RSSI.
4. The heatmap is correctly layered over the floor plan with sample markers and detailed hover
   readings above it.
5. SSID, BSSID, and band filtering works and does not trigger scans.
6. Point deletion and CSV export correctly handle band-aware measurements.
7. Automated tests cover the new numerical and data behavior and the full suite passes.
8. Formatting, linting, Bandit, detect-secrets, and other configured pre-commit hooks pass.
9. Documentation, `uv.lock`, CI, and the binary release workflow remain consistent with the
   implementation.
10. The final diff contains no credentials, generated build output, caches, or unrelated changes.

Where macOS hardware behavior cannot be exercised in the current environment, use representative
CoreWLAN test doubles and explicitly report the remaining real-Mac smoke-test steps. Do not claim
that native scanning or the frozen macOS binary was runtime-verified unless it actually was.
