"""Every OS-specific behavior Wingvox needs, in one place, dispatched by
platform.system(). Mac bodies exist to document parity with the Windows
ones; flow.py imports names from here instead of branching inline."""

import os
import platform
import subprocess
import sys
import threading
from pathlib import Path

from pynput import keyboard

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Cmd+V on Mac, Ctrl+V everywhere else.
PASTE_MODIFIER = keyboard.Key.cmd if IS_MAC else keyboard.Key.ctrl

# Physical Right Alt/Option. On non-US Windows keyboard layouts, pynput can
# report the same physical key as alt_gr instead of alt_r depending on
# layout/driver — check membership against this tuple, not equality against
# a single Key, so international users aren't silently locked out.
HOTKEY_KEYS = (keyboard.Key.alt_r,) if IS_MAC else (keyboard.Key.alt_r, keyboard.Key.alt_gr)


# ---------- clipboard ----------

def clipboard_get() -> str:
    if IS_MAC:
        return subprocess.run(["pbpaste"], capture_output=True).stdout.decode("utf-8", "replace")
    import pyperclip
    return pyperclip.paste()


def clipboard_set(text: str) -> None:
    if IS_MAC:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return
    import pyperclip
    pyperclip.copy(text)


# ---------- single-instance lock ----------

def lock_exclusive_nb(f) -> bool:
    """Try to take an exclusive, non-blocking lock on open file handle f.
    Released automatically by the OS on normal process exit either way."""
    if IS_WINDOWS:
        import msvcrt
        f.write(str(os.getpid()))
        f.flush()
        f.seek(0)  # msvcrt.locking locks from the current file position
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        f.write(str(os.getpid()))
        f.flush()
        return True


# ---------- data directory ----------

def data_dir() -> Path:
    """Where dictionary.txt/corrections.txt/wingvox.lock/wingvox.log live.
    Repo-relative on Mac (unchanged from before this file existed). On
    Windows, a PyInstaller onedir install location may not be writable and
    isn't the right place for user data regardless, so use %LOCALAPPDATA%."""
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Wingvox"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).parent


# ---------- Windows: no console under a --windowed PyInstaller build ----------

def setup_windows_console_log(log_path: Path) -> None:
    """A --windowed frozen exe has no console at all, so print()/stderr have
    nowhere to go (and can raise on some builds where sys.stdout is None).
    Task Scheduler, unlike launchd's StandardOutPath, doesn't capture
    stdout/stderr for us, so redirect them to a file ourselves."""
    if not IS_WINDOWS:
        return
    log = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = log
    sys.stderr = log


# ---------- Windows: deep-link into the privacy settings page ----------

def open_privacy_settings(page: str = "microphone") -> None:
    """There's no programmatic way to query or trigger the Windows mic/
    consent prompt the way macOS's AVFoundation does — the best available
    is deep-linking the user into the right Settings page."""
    if not IS_WINDOWS:
        return
    try:
        os.startfile(f"ms-settings:privacy-{page}")
    except Exception:
        pass


# ---------- Windows: prefer WASAPI over PortAudio's default host API ----------

def default_windows_input_device(sd):
    """PortAudio's default host API on Windows is often MME (higher latency,
    occasionally flaky) rather than WASAPI. Return WASAPI's default input
    device index, or None (caller falls back to the system default)."""
    if not IS_WINDOWS:
        return None
    try:
        hostapis = sd.query_hostapis()
        for i, api in enumerate(hostapis):
            if "wasapi" in api["name"].lower():
                idx = api.get("default_input_device", -1)
                return idx if idx >= 0 else None
    except Exception:
        pass
    return None
