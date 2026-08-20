"""faster-whisper (CTranslate2) transcription backend for Intel Macs.

mlx (stt_mac.py's backend) has no x86_64 build -- Apple-Silicon architecture
only, not a version gap. faster-whisper's ctranslate2 dependency does publish
native macosx_11_0_x86_64 wheels, so Intel Macs reuse the same CTranslate2
pipeline already proven out for Windows in stt_windows.py. This is a
re-export: run_model's contract and every tuning decision (beam_size=1,
vad_filter, etc.) come from stt_windows.py unchanged -- only the default
model differs, and only because Windows's default would silently break
Wingvox's language.txt feature here (see below)."""

import os

# Windows defaults to "small.en" (CPU-only, no multilingual need existed when
# that default was chosen). Intel Mac is CPU-only too, but Wingvox now has a
# per-install multilingual feature (language.txt/KNOWN_LANGUAGES/
# set-language.sh, see flow.py) that "small.en" would silently break for any
# non-English Intel Mac user. Default to multilingual "small" instead so
# language.txt works out of the box; override with WINGVOX_WHISPER_MODEL as
# on Windows. Must run before the stt_windows import below, which is what
# actually triggers stt_windows.py's module-level WHISPER_MODEL read.
os.environ.setdefault("WINGVOX_WHISPER_MODEL", "small")

from stt_windows import run_model, WHISPER_MODEL, _get_model  # noqa: F401,E402
