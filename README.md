# macOS Wi-Fi Mapper

An interactive Wi-Fi site-survey tool for macOS. Upload a floor plan, click where
you are standing, and the app scans every visible access point through Apple's
native CoreWLAN framework. Measurements can be filtered, visualized, removed,
and exported as CSV.

## Install from a release

Download the archive for your Mac from the latest GitHub release:

- `wifi-site-survey-macos-arm64.tar.gz` for Apple Silicon
- `wifi-site-survey-macos-x86_64.tar.gz` for Intel

Then extract and run it:

```bash
tar -xzf wifi-site-survey-macos-*.tar.gz
./wifi-site-survey
```

The executable starts a local Streamlit server and opens the app in your browser.
macOS may require you to allow the binary in **System Settings → Privacy &
Security**, and CoreWLAN may require Location Services permission for your
terminal or Python host.

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

Push a semantic-version tag to build both macOS architectures and publish a
GitHub release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The release workflow builds one self-contained executable per architecture,
packages it with executable permissions intact, and publishes SHA-256 checksums.

## Data and privacy

Survey data stays in the Streamlit session until downloaded as CSV. The app does
not upload floor plans or Wi-Fi measurements anywhere.
