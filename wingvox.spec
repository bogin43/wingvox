# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Wingvox on Windows. Build with:
#   pyinstaller wingvox.spec
#
# Onedir, not onefile: onefile re-extracts to a fresh temp dir on every
# launch, adding real latency to every login (Wingvox is a background app
# that starts at logon), and the self-extracting pattern trips AV/
# SmartScreen heuristics harder than a plain folder of files does.
#
# Model weights are NOT bundled -- faster-whisper lazy-downloads them into
# the Hugging Face cache on first run, the same strategy stt_mac.py's
# mlx-whisper already uses on the Mac side. Keeps the installer/download
# small and avoids repackaging on every model bump.

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

# dictionary.default.txt/corrections.txt are NOT bundled here: flow.py never
# reads either from a path relative to itself (both go through
# platform_compat.data_dir(), i.e. %LOCALAPPDATA%\Wingvox at runtime), so
# bundling them would be dead weight. corrections.txt is also gitignored
# (personal, user-generated via `add-correction`) and won't exist on a
# fresh clone -- referencing it here would break the very first build.
datas = []

binaries = []
hiddenimports = []

for pkg in ("faster_whisper", "ctranslate2"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# sounddevice ships a bundled PortAudio DLL as package data -- default
# import scanning misses it.
datas += collect_data_files("sounddevice")

# No .ico has been designed yet (logo redesign is a separate deferred task)
# -- fall back to PyInstaller's default rather than pointing at a path that
# doesn't exist.
_icon_path = os.path.join("assets", "wingvox.ico")
icon = _icon_path if os.path.exists(_icon_path) else None

a = Analysis(
    ["flow.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Wingvox",
    console=False,  # --windowed: a background app, no console window
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Wingvox",
)
