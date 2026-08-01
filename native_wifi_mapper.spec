# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir recipe for the native PySide6 macOS application."""

from PyInstaller.utils.hooks import collect_all


pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")

a = Analysis(
    ["native_wifi_mapper.py"],
    pathex=[],
    binaries=pyside_binaries,
    datas=[("THIRD_PARTY_NOTICES.md", "."), *pyside_datas],
    hiddenimports=[*pyside_hidden, "objc", "CoreWLAN", "CoreLocation", "AppKit"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit", "plotly", "streamlit_plotly_events"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="wifi-site-survey-native",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="wifi-site-survey-native",
)
app = BUNDLE(
    coll,
    name="WiFi Site Survey Native.app",
    icon=None,
    bundle_identifier="com.steffenschumacher.wifisitesurvey",
    version="0.3.0",
    info_plist={
        "CFBundleDisplayName": "WiFi Site Survey Native",
        "NSLocationUsageDescription": (
            "WiFi Site Survey needs Location Services permission because macOS protects nearby "
            "Wi-Fi network names and access-point addresses as location information."
        ),
        "NSLocationWhenInUseUsageDescription": (
            "WiFi Site Survey uses permission only to read SSID and BSSID values during a scan."
        ),
    },
)
