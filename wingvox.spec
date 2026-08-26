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

# ctranslate2's wheel vendors its own msvcp140.dll/vcruntime140.dll for
# portability -- a build from mid-2015 (VS2015 RTM), predating
# vcruntime140_1.dll entirely. onnxruntime (pulled in by faster-whisper's
# vad_filter) vendors that newer vcruntime140_1.dll alongside it in the same
# _internal folder. Windows' DLL search order tries the app directory before
# System32, so the OLD bundled msvcp140.dll -- not whatever's actually
# installed on the machine -- is what loads, right next to a vcruntime140_1
# built for a much newer CRT. Confirmed by reproducing the crash: an
# access-violation (0xc0000005) inside that bundled msvcp140.dll, right as
# WhisperModel() initializes ctranslate2's native runtime.
# install.ps1 now installs the real Visual C++ Redistributable as a
# prerequisite (see its "Visual C++ Redistributable" step) specifically so a
# complete, mutually-consistent set of these DLLs is always present in
# System32 -- so drop the vendored ones and let the OS supply them instead of
# shipping a stale, conflicting copy. Matched by exact basename only: numpy
# vendors its own copy too, but under a hash-suffixed filename
# (numpy.libs\msvcp140-<hash>.dll) that Windows' loader never confuses with
# the plain system one, so it's left alone.
#
# These DLLs don't actually come in through collect_all()'s own binaries list
# above (verified empty for both packages) -- Analysis() does its own
# recursive PE-import walk on every collected binary and re-discovers them as
# transitive dependencies regardless of what's passed into binaries=, adding
# them straight to a.binaries. Filtering the binaries= input before Analysis()
# runs is a no-op; a.binaries after Analysis() is what actually has to be
# filtered.
_VC_RUNTIME_DLLS = {
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
    "concrt140.dll", "vcomp140.dll", "vccorlib140.dll",
}

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
a.binaries = [
    b for b in a.binaries
    if os.path.basename(b[0]).lower() not in _VC_RUNTIME_DLLS
    and os.path.basename(b[1]).lower() not in _VC_RUNTIME_DLLS
]
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
