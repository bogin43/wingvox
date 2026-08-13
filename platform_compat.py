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

# install.ps1 always installs x64 Python -- faster-whisper's ctranslate2
# dependency has no Windows ARM64 wheels, so every Windows install of this
# app runs x64 Python even on ARM64 hardware. But platform.machine() reports
# the host's real ARM64 architecture regardless of that process-level x64
# emulation, and sounddevice's bundled-PortAudio binary selection (a
# module-level check in sounddevice.py) trusts platform.machine() at face
# value -- it picks the ARM64-native DLL and fails to load it into this x64
# process (WinError 0x7e). Patch it before sounddevice is ever imported so
# it sees this process's actual x64 architecture instead of the host's.
if IS_WINDOWS and platform.machine().lower() in ("arm64", "aarch64"):
    platform.machine = lambda: "AMD64"

# Cmd+V on Mac, Ctrl+V everywhere else.
PASTE_MODIFIER = keyboard.Key.cmd if IS_MAC else keyboard.Key.ctrl

# Physical Right Alt/Option. On non-US Windows keyboard layouts, pynput can
# report the same physical key as alt_gr instead of alt_r depending on
# layout/driver — check membership against this tuple, not equality against
# a single Key, so international users aren't silently locked out.
#
# Left Alt is deliberately absent. Some virtualized keyboard paths (UTM's,
# notably) deliver a physical right-side Alt as VK_LMENU, which makes Left
# Alt tempting to accept -- but on ordinary hardware Left Alt prefixes
# Alt+Tab, Alt+F4, Alt+Space and every Alt+<letter> menu, so accepting it
# means all of those open the mic and start a recording.
HOTKEY_KEYS = (keyboard.Key.alt_r,) if IS_MAC else (
    keyboard.Key.alt_r, keyboard.Key.alt_gr,
)

if IS_WINDOWS:
    import ctypes
    VK_RMENU = 0xA5

    def is_hotkey_physically_down() -> bool:
        """pynput's low-level keyboard hook has been observed to silently
        drop the on_release callback for Right Alt/AltGr specifically on
        some Windows setups (seen under UTM VM keyboard passthrough) --
        the press fires, the matching release never does, leaving a
        recording stuck open forever. GetAsyncKeyState reads the actual
        current hardware key state directly from Windows, independent of
        whatever the hook chose to deliver, so callers can poll it as a
        fallback for a release the hook missed. Checks exactly the key
        HOTKEY_KEYS accepts -- polling Left Alt too would keep a recording
        alive for an unrelated Alt+Tab."""
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_RMENU) & 0x8000)
else:
    def is_hotkey_physically_down() -> bool:
        return False


# ---------- macOS permissions ----------

# The LaunchAgent's label, used to restart ourselves through launchd once a
# permission is granted. Must match com.broganwilliams.wingvox.plist.template.
LAUNCH_AGENT_LABEL = "com.broganwilliams.wingvox"


def has_accessibility_access() -> bool:
    """Whether Accessibility is already granted. Never prompts."""
    if not IS_MAC:
        return True
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return True  # can't determine -- fail open rather than false-alarm


def request_accessibility_access() -> bool:
    """Same check, but shows the system prompt when not yet trusted.

    Unlike Microphone (where AVFoundation's dialog has an Allow button that
    grants access outright), Apple deliberately gives Accessibility no
    inline approval: the dialog only offers "Open System Settings", and the
    user has to flip the toggle themselves. What this buys is that macOS
    pre-adds Wingvox to the list already, so they flip a switch instead of
    hunting for the app with + and Cmd+Shift+G."""
    if not IS_MAC:
        return True
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt,
        )
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return True


def has_input_monitoring() -> bool:
    """Whether we're allowed to listen for key presses.

    Normally true purely as a consequence of Accessibility being granted --
    macOS treats an Accessibility-trusted app as allowed to listen, and
    Wingvox won't even appear in the Input Monitoring list. Checked
    separately anyway so the rare machine where that doesn't hold gets a
    prompt instead of a hotkey that silently does nothing."""
    if not IS_MAC:
        return True
    try:
        from Quartz import CGPreflightListenEventAccess
        return bool(CGPreflightListenEventAccess())
    except Exception:
        return True


def request_input_monitoring() -> None:
    if not IS_MAC:
        return
    try:
        from Quartz import CGRequestListenEventAccess
        CGRequestListenEventAccess()
    except Exception:
        pass


def restart_self() -> None:
    """Restart Wingvox through launchd.

    Accessibility trust is decided when the process starts, so a grant made
    while Wingvox is running doesn't take effect until it restarts. Without
    this the user flips the toggle, nothing happens, and it looks broken --
    the single most common way this setup goes wrong."""
    if not IS_MAC:
        return
    subprocess.Popen(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ---------- clipboard ----------

def clipboard_get():
    """Current clipboard text, or None when the clipboard holds something
    that isn't text at all (an image, copied files, ...).

    The None case matters: inject() saves this value, pastes, then restores
    it. pyperclip.paste() returns '' both for "empty text" and for "there is
    no text here, it's a screenshot" -- so without this check, dictating
    while an image is on the clipboard silently replaced that image with an
    empty string. Ask Windows which formats are actually present instead
    (IsClipboardFormatAvailable needs no clipboard ownership), and report
    None so callers know there is nothing safe to restore."""
    if IS_MAC:
        return subprocess.run(["pbpaste"], capture_output=True).stdout.decode("utf-8", "replace")
    import ctypes
    CF_TEXT, CF_UNICODETEXT = 1, 13
    user32 = ctypes.windll.user32
    if not (user32.IsClipboardFormatAvailable(CF_UNICODETEXT)
            or user32.IsClipboardFormatAvailable(CF_TEXT)):
        return None
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
        # Lock BEFORE writing, matching the POSIX branch's order below --
        # Windows enforces a locked byte range at the OS level even against
        # plain writes from another handle, not just against competing lock
        # attempts. Writing first meant a second instance's write/flush
        # threw a raw PermissionError instead of this function cleanly
        # returning False.
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            f.write(str(os.getpid()))
            f.flush()
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


# ---------- Windows: clear any stuck modifier before a simulated paste ----------

def release_all_modifiers(kb) -> None:
    """Right Alt commonly maps to AltGr on Windows, and AltGr's key-down
    generates a *synthetic* Ctrl-down alongside its own as an OS-level side
    effect. If that synthetic Ctrl's matching key-up is ever missed -- more
    likely through a virtualized keyboard input path -- Windows is left
    thinking Ctrl is still held down, which can make some apps' Ctrl+V
    handling miss an injected paste combo entirely. Releasing a key that
    isn't actually down is a harmless no-op, so it's safe to unconditionally
    clear everything right before pasting."""
    if not IS_WINDOWS:
        return
    for key in (
        keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
        keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr,
        keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
        keyboard.Key.cmd,
    ):
        try:
            kb.release(key)
        except Exception:
            pass


# ---------- Windows: no console under a --windowed PyInstaller build ----------

def setup_windows_console_log(log_path: Path, max_bytes: int = 5_000_000) -> None:
    """A --windowed frozen exe has no console at all, so print()/stderr have
    nowhere to go (and can raise on some builds where sys.stdout is None).
    Task Scheduler, unlike launchd's StandardOutPath, doesn't capture
    stdout/stderr for us, so redirect them to a file ourselves.

    Wingvox runs at every logon and appends for the life of the install, so
    rotate once past max_bytes (keeping a single .old generation) rather than
    growing one file without bound forever."""
    if not IS_WINDOWS:
        return
    try:
        if log_path.exists() and log_path.stat().st_size > max_bytes:
            previous = log_path.parent / (log_path.name + ".old")
            previous.unlink(missing_ok=True)
            log_path.rename(previous)
    except OSError:
        pass  # rotation is best-effort; never block startup over it
    log = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = log
    sys.stderr = log


# ---------- Windows: start Ollama without a console window ----------

def find_ollama() -> str:
    """Full path to ollama.exe, or "" if it isn't installed."""
    if not IS_WINDOWS:
        return ""
    import shutil
    found = shutil.which("ollama")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        if base:
            candidate = Path(base) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.exists():
                return str(candidate)
    return ""


def start_ollama_background() -> bool:
    """Launch `ollama serve` with no console window, detached so it outlives
    Wingvox. Returns whether a launch was attempted.

    On the Mac, `brew services start ollama` gives Ollama real background
    persistence and nothing here is needed. Windows has no equivalent:
    ollama.exe is a CONSOLE-subsystem binary, so any logon-time launch of it
    puts a terminal window on the user's screen. That window looks like
    leftover clutter, and closing it -- the obvious thing to do -- kills
    Ollama, after which Wingvox silently falls back to pasting raw,
    uncleaned transcripts with nothing on screen explaining why.

    CREATE_NO_WINDOW suppresses the console entirely; DETACHED_PROCESS keeps
    the server alive independently of Wingvox. Ollama's own `ollama app.exe`
    (GUI-subsystem, tray icon) would be the tidier answer, but it exits
    immediately with status 1 when Task Scheduler starts it, so driving
    ollama.exe directly is the reliable path."""
    if not IS_WINDOWS:
        return False
    exe = find_ollama()
    if not exe:
        return False
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    try:
        subprocess.Popen(
            [exe, "serve"],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except Exception:
        return False


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
