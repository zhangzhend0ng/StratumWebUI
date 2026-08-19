# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Stratum WebUI (onedir, console).

Build (repo root, inside the build venv — or just run packaging/build.ps1):
    pyinstaller packaging/StratumWebUI.spec --noconfirm

Produces:
    dist/StratumWebUI/StratumWebUI.exe
    dist/StratumWebUI/_internal/index.html + Python runtime

bin/stratum.exe and VERSION.txt are SDK release artifacts and are NOT bundled
here; build.ps1 copies them next to the exe afterwards, making dist/StratumWebUI
a self-contained portable app that the Inno Setup script then packages.

console=True on purpose: the log stays visible, Ctrl+C exits, and subprocess
spawns of stratum.exe inherit the console (no flashing windows).
"""

import os

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = this file's directory

a = Analysis(
    [os.path.join(ROOT, "server.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, f), ".")
           for f in ("index.html", "report.js", "stl-preview.js")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StratumWebUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=os.path.join(SPECPATH, "stratum-webui.ico"),  # regenerate: make_icon.py
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StratumWebUI",
)
