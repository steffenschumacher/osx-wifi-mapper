# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir recipe for the Windows PySide6 application."""

a = Analysis(
    ["native_wifi_mapper.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("THIRD_PARTY_NOTICES.md", "."),
        ("LICENSES/GPL-3.0-only.txt", "LICENSES"),
        ("LICENSES/LGPL-3.0-only.txt", "LICENSES"),
    ],
    hiddenimports=["windows_wifi", "wifi_scanner"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "CoreLocation",
        "CoreWLAN",
        "objc",
        "plotly",
        "streamlit",
        "streamlit_plotly_events",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="WiFi Site Survey",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version="packaging/windows-version-info.txt",
)
diagnostics = Analysis(
    ["wifi_diagnostics.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["windows_wifi", "wifi_scanner"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "CoreLocation",
        "CoreWLAN",
        "numpy",
        "objc",
        "pandas",
        "PIL",
        "plotly",
        "PySide6",
        "streamlit",
        "streamlit_plotly_events",
    ],
    noarchive=False,
    optimize=0,
)
diagnostics_pyz = PYZ(diagnostics.pure)
diagnostics_exe = EXE(
    diagnostics_pyz,
    diagnostics.scripts,
    [],
    name="WiFi Site Survey Diagnostics",
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    version="packaging/windows-version-info.txt",
)
coll = COLLECT(
    exe,
    diagnostics_exe,
    a.binaries,
    a.datas,
    diagnostics.binaries,
    diagnostics.datas,
    strip=False,
    upx=False,
    name="WiFi Site Survey",
)
