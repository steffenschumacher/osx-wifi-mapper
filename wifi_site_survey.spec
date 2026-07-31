# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a location-aware macOS app bundle."""

from PyInstaller.utils.hooks import collect_all


streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
events_datas, events_binaries, events_hidden = collect_all("streamlit_plotly_events")

a = Analysis(
    ["wifi_site_survey_launcher.py"],
    pathex=[],
    binaries=[*streamlit_binaries, *events_binaries],
    datas=[("wifi_site_survey.py", "."), *streamlit_datas, *events_datas],
    hiddenimports=[
        *streamlit_hidden,
        *events_hidden,
        "objc",
        "CoreWLAN",
        "CoreLocation",
        "AppKit",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wifi-site-survey",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name="WiFi Site Survey.app",
    icon=None,
    bundle_identifier="com.steffenschumacher.wifisitesurvey",
    version="0.2.2",
    info_plist={
        "CFBundleDisplayName": "WiFi Site Survey",
        # The application presents its UI in the browser, so it should not appear as an
        # unresponsive, windowless application in the Dock.
        "LSUIElement": True,
        "NSLocationUsageDescription": (
            "WiFi Site Survey needs Location Services permission because macOS protects nearby "
            "Wi-Fi network names and access-point addresses as location information."
        ),
        "NSLocationWhenInUseUsageDescription": (
            "WiFi Site Survey uses permission only to read SSID and BSSID values during a scan."
        ),
    },
)
