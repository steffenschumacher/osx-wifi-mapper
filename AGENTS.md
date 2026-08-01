# Contributor Instructions

## Development workflow

- Use `uv` for dependency management and run commands through `uv run` when available.
- Keep `uv.lock` committed and synchronized with `pyproject.toml`.
- Before committing, run:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run bandit -c pyproject.toml -r .`
  - `uv run pytest`
- Preserve unrelated user changes and never commit generated `build/`, `dist/`, cache, or credential
  files.

## Application constraints

- Keep the macOS bundle identifier `com.steffenschumacher.wifisitesurvey` stable. Location Services
  and SSID/BSSID access depend on the bundle's TCC identity.
- Do not use `sudo` for CoreWLAN scans. SSID/BSSID access requires Location Services permission.
- The UI is browser-backed Streamlit, but the release is a standard PyInstaller onedir `.app`.
  Do not switch back to a onefile/windowed bundle; PyInstaller does not recommend that combination
  on macOS.
- Bind the server only to loopback, keep Streamlit production mode explicit, and open the browser
  only after the health endpoint responds.
- Maintain the single-instance lock and the in-app quit path when changing launcher behavior.

## Map and data compatibility

- Floor-plan coordinates use an isotropic width-normalized coordinate system. Preserve the source
  image aspect ratio and apply calibration uniformly to both axes.
- Plotly traces consumed by `streamlit-plotly-events` must receive plain JSON lists. Do not pass
  NumPy arrays or Pandas Series directly; Plotly 6 binary typed-array serialization is incompatible
  with the embedded component and can make traces or clicks disappear.
- Keep SSID, BSSID, and band filters independently optional. Multiple matching triples combine by
  strongest (maximum) interpolated RSSI.
- A triple needs five two-dimensionally spread sample points at least one metre apart.
- Treat `.wifisurvey` as a versioned external file format. Validate imported archives, preserve
  backward compatibility when feasible, and increment the format version only for incompatible
  changes.

## Releases

- Synchronize the application version in `pyproject.toml`, `uv.lock`, and
  `wifi_site_survey.spec`.
- Release tags use `vMAJOR.MINOR.PATCH` and trigger `.github/workflows/release.yml`.
- Releases must build both `arm64` and `x86_64` app bundles.
- The workflow must package with macOS symlinks and permissions intact, then extract, verify, and
  launch the exact downloadable archive. Keep health, root-HTML, signature, and port-3000 checks.
- Never place a PAT or signing credential in repository files, logs, workflow definitions, or Git
  remotes.
