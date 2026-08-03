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

- The released UI is the shared, browser-free PySide6 Widgets application. Keep platform-specific
  scanning behind `wifi_scanner.py`; do not add a browser or local server to the native release.
- Keep the macOS bundle identifier `com.steffenschumacher.wifisitesurvey` stable. Location Services
  and SSID/BSSID access depend on the bundle's TCC identity.
- Do not use `sudo` for CoreWLAN scans. SSID/BSSID access requires Location Services permission.
- Windows scans use the Win32 Native Wi-Fi API, run as the signed-in user, and require Windows
  precise-location/desktop-app consent. Never request elevation or parse `netsh` output for scans.
- Native Wi-Fi imports must remain platform-guarded so Linux tests and the other OS can import the
  shared UI.
- Keep macOS and Windows releases as PyInstaller onedir artifacts. Do not switch to onefile bundles.

## Map and data compatibility

- Floor-plan coordinates use an isotropic width-normalized coordinate system. Preserve the source
  image aspect ratio and apply calibration uniformly to both axes.
- Keep SSID, BSSID, and band filters independently optional. Multiple matching triples combine by
  strongest (maximum) interpolated RSSI.
- A triple needs five two-dimensionally spread sample points at least one metre apart.
- Treat `.wifisurvey` as a versioned external file format. Validate imported archives, preserve
  backward compatibility when feasible, and increment the format version only for incompatible
  changes.

## Releases

- Synchronize the application version in `pyproject.toml`, `uv.lock`, `native_wifi_mapper.spec`,
  and the retained legacy `wifi_site_survey.spec`.
- Release tags use `vMAJOR.MINOR.PATCH` and trigger `.github/workflows/release.yml`.
- Releases must build macOS `arm64`, macOS `x86_64`, and Windows `x86_64`. Do not claim Windows
  ARM64 support without a native build and hardware test.
- Workflows must extract, launch, and terminate the exact downloadable archives and confirm the
  native apps open no TCP listener. Preserve macOS symlinks, permissions, metadata, and signatures.
- Do not publish Windows release assets until physical Windows 11 Wi-Fi scanning has been manually
  verified.
- Never place a PAT or signing credential in repository files, logs, workflow definitions, or Git
  remotes.
