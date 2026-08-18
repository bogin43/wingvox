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

# Physical Right Alt/Option, Wingvox's original and default hotkey. On
# non-US Windows keyboard layouts, pynput can report the same physical key
# as alt_gr instead of alt_r depending on layout/driver -- check membership
# against a tuple, not equality against a single Key, so international
# users aren't silently locked out.
HOTKEY_KEYS = (keyboard.Key.alt_r,) if IS_MAC else (
    keyboard.Key.alt_r, keyboard.Key.alt_gr,
)

# Mac only: Left Option as a user-chosen alternative to the default above.
# Never offered as the default itself -- on ordinary hardware it prefixes
# Alt+Tab, Alt+F4, Alt+Space and every Alt+<letter> menu (Option+drag,
# Option+click, Option+Space for the dictionary lookup on Mac), so accepting
# it unconditionally would mean all of those open the mic instead. As
# something the user deliberately opts into via hotkey.txt, trading those
# away is their call to make, not Wingvox's to make for them. Not offered on
# Windows: Left Alt was tried there and reverted (see install.sh history) for
# the identical Alt+Tab/Alt+F4 conflict, and Windows has no per-user hotkey
# picker yet to make it an informed opt-in rather than a silent default.
MAC_HOTKEY_LABELS = {"right": "Right Option", "left": "Left Option"}


def mac_hotkey_keys(choice: str):
    """pynput Key objects for the given Mac hotkey choice. Any value other
    than "left" resolves to "right" -- a corrupted or hand-edited
    hotkey.txt should degrade to Wingvox's known-good default, not to no
    hotkey working at all."""
    if choice == "left":
        return (keyboard.Key.alt_l,)
    return (keyboard.Key.alt_r,)


if IS_WINDOWS:
    import ctypes
    VK_RMENU = 0xA5

    def is_hotkey_physically_down(_choice: str = "right") -> bool:
        """Whether the dictation key is physically held right now, read from
        the hardware rather than from the keyboard hook.

        The hook has been observed to silently drop the release event for
        the dictation key (seen under UTM VM keyboard passthrough): the
        press fires, the matching release never does, and the recording
        stays open forever. Callers poll this as a backstop. It reports on
        exactly the key HOTKEY_KEYS accepts -- polling Left Alt too would
        end a recording on an unrelated Alt+Tab.

        Windows has no hotkey choice yet, so _choice is accepted (to keep
        one call signature across platforms) and ignored."""
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_RMENU) & 0x8000)
elif IS_MAC:
    # Apple's virtual keycodes are physical positions, not characters, so
    # these are stable across keyboard layouts.
    _KVK_RIGHT_OPTION = 61
    _KVK_LEFT_OPTION = 58
    _MAC_HOTKEY_VK = {"right": _KVK_RIGHT_OPTION, "left": _KVK_LEFT_OPTION}

    def is_hotkey_physically_down(choice: str = "right") -> bool:
        """Mac counterpart of the Windows check above. Same purpose: a
        dropped release must not be able to wedge a recording open, and a
        wedged recording can only be cleared by restarting the app."""
        try:
            from Quartz import CGEventSourceKeyState, kCGEventSourceStateHIDSystemState
            return bool(CGEventSourceKeyState(
                kCGEventSourceStateHIDSystemState,
                _MAC_HOTKEY_VK.get(choice, _KVK_RIGHT_OPTION),
            ))
        except Exception:
            # Can't read the hardware -- claim the key is still down so the
            # watchdog never ends a recording the user is in the middle of.
            return True
else:
    def is_hotkey_physically_down(_choice: str = "right") -> bool:
        return True


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
        # pbpaste prints nothing and exits 0 for an image or copied files, so
        # it can't distinguish "empty text" from "not text at all" any better
        # than pyperclip can. Ask the pasteboard which types it actually
        # holds first, so the None contract above is true on both platforms.
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            board = NSPasteboard.generalPasteboard()
            if not board.availableTypeFromArray_([NSPasteboardTypeString]):
                return None
            # Read through the same pasteboard we just asked, rather than
            # forking pbpaste for text AppKit already has -- this sits on the
            # paste path, inside the inject lock, before the keystroke.
            text = board.stringForType_(NSPasteboardTypeString)
            if text is not None:
                return str(text)
        except Exception:
            pass  # can't determine -- fall through and treat it as text
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


# ---------- update check ----------

def install_dir() -> Path:
    """The git checkout Wingvox runs from. Distinct from data_dir(): on
    Windows those are different places, and the update check has to look at
    the checkout, not at %LOCALAPPDATA%."""
    return Path(__file__).resolve().parent


def _git(*args, timeout=10):
    """Run git in the install directory. Returns stripped stdout, or None on
    any failure at all -- git missing, not a checkout, no network, timeout.
    The update check is a nicety; it must never be a reason the app is
    slower to start or noisier in the log."""
    try:
        r = subprocess.run(
            ["git", "-C", str(install_dir()), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def update_command() -> str:
    """The one line a user runs to take an update. Kept here so the pill,
    the log and the docs can't drift apart."""
    if IS_MAC:
        return (f"cd {install_dir()} && git pull && "
                f"launchctl kickstart -k gui/$(id -u)/{LAUNCH_AGENT_LABEL}")
    return (f"cd {install_dir()} && git pull, then run wingvox-off.cmd "
            "followed by wingvox-on.cmd")


def check_for_update():
    """Is a newer commit published than the one running?

    Returns True (behind), False (current), or None (couldn't tell).

    Read-only on purpose: `git ls-remote` asks the remote for its ref without
    writing anything into the user's checkout, so this can't create a dirty
    tree, a detached head, or a surprise merge. Deciding "behind" by SHA
    inequality alone would be wrong on the development machine, where local
    is *ahead* of the remote -- so the remote SHA is only treated as an
    update when the local repository has never seen that commit.
    """
    local = _git("rev-parse", "HEAD")
    if not local:
        return None
    remote_line = _git("ls-remote", "origin", "HEAD", timeout=15)
    if not remote_line:
        return None
    remote = remote_line.split()[0]
    if remote == local:
        return False
    # `git cat-file -e` succeeds only if this repo already has that object.
    have_it = _git("cat-file", "-e", f"{remote}^{{commit}}")
    return have_it is None


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

def rotate_log(log_path: Path, max_bytes: int = 5_000_000) -> None:
    """Keep one .old generation once the log passes max_bytes.

    Call it before the file is opened for writing.

    Windows only, despite the platform-neutral shape. On the Mac launchd
    opens wingvox.log itself (StandardOutPath in the plist) and hands the
    process an already-open descriptor, so renaming the file at startup
    doesn't redirect anything -- the whole session keeps writing into
    wingvox.log.old, which the next rotation then deletes. Rotating a
    launchd-owned stream has to happen outside the app (a newsyslog.d
    entry), or the app has to stop using StandardOutPath and open its own
    log on both platforms. Until then the Mac log still grows unbounded."""
    try:
        if log_path.exists() and log_path.stat().st_size > max_bytes:
            previous = log_path.parent / (log_path.name + ".old")
            previous.unlink(missing_ok=True)
            log_path.rename(previous)
    except OSError:
        pass  # best-effort; never block startup over it


def setup_windows_console_log(log_path: Path) -> None:
    """A --windowed frozen exe has no console at all, so print()/stderr have
    nowhere to go (and can raise on some builds where sys.stdout is None).
    Task Scheduler, unlike launchd's StandardOutPath, doesn't capture
    stdout/stderr for us, so redirect them to a file ourselves."""
    if not IS_WINDOWS:
        return
    rotate_log(log_path)  # must happen before the file is opened for append
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

    On the Mac this is `brew services start ollama`, the same thing
    install.sh runs. It matters after the install too: if that service is
    stopped, or was never started, Wingvox would otherwise paste raw
    uncleaned transcripts indefinitely while the identical situation on
    Windows silently repaired itself.

    Windows has no service equivalent: ollama.exe is a CONSOLE-subsystem
    binary, so any logon-time launch of it
    puts a terminal window on the user's screen. That window looks like
    leftover clutter, and closing it -- the obvious thing to do -- kills
    Ollama, after which Wingvox silently falls back to pasting raw,
    uncleaned transcripts with nothing on screen explaining why.

    CREATE_NO_WINDOW suppresses the console entirely; DETACHED_PROCESS keeps
    the server alive independently of Wingvox. Ollama's own `ollama app.exe`
    (GUI-subsystem, tray icon) would be the tidier answer, but it exits
    immediately with status 1 when Task Scheduler starts it, so driving
    ollama.exe directly is the reliable path."""
    if IS_MAC:
        import shutil
        if not shutil.which("brew"):
            return False
        try:
            subprocess.Popen(
                ["brew", "services", "start", "ollama"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False
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

def wasapi_hostapi_index(sd):
    """Index of PortAudio's WASAPI host API, or None if there isn't one.

    Single source of truth for "which host API is WASAPI". Two callers need
    it and they must agree: one picks the default input device, the other
    decides whether WasapiSettings may be attached to a stream. When these
    were separate implementations they matched the name differently (one
    case-insensitively, one not), so a PortAudio build spelling it any other
    way would have silently dropped the WASAPI format conversion while still
    selecting a WASAPI device."""
    if not IS_WINDOWS:
        return None
    try:
        for i, api in enumerate(sd.query_hostapis()):
            if "wasapi" in api["name"].lower():
                return i
    except Exception:
        pass
    return None


def default_windows_input_device(sd):
    """PortAudio's default host API on Windows is often MME (higher latency,
    occasionally flaky) rather than WASAPI. Return WASAPI's default input
    device index, or None (caller falls back to the system default)."""
    if not IS_WINDOWS:
        return None
    try:
        for api in sd.query_hostapis():
            if "wasapi" in api["name"].lower():
                device = api.get("default_input_device", -1)
                return device if device >= 0 else None
    except Exception:
        pass
    return None


# CoreAudio's fixed identifier for a Mac's internal microphone hardware,
# stable across every model that has one (unlike its display name, which is
# "MacBook Air Microphone" on an Air and "MacBook Pro Microphone" on a Pro).
_BUILTIN_MIC_UID = "BuiltInMicrophoneDevice"


def mac_builtin_mic_name():
    """The real name CoreAudio gave this Mac's built-in microphone, or None
    if there isn't one (a Mac mini/Studio/Pro with no internal mic) or it
    can't be determined.

    Matching a hardcoded string like "MacBook Air Microphone" only works on
    an Air. The tempting fix -- AVCaptureDevice.defaultDeviceWithDeviceType_
    mediaType_position_(AVCaptureDeviceTypeBuiltInMicrophone, ...) -- turns
    out not to work at all: modern macOS collapsed every distinct mic type
    into one generic AVCaptureDeviceTypeMicrophone, so that call ignores the
    "built-in" request and just hands back the current system default. On a
    machine with Bluetooth headphones connected, that reintroduces the exact
    bug this function exists to avoid. Discovering every AVCaptureDeviceType
    Microphone and matching by uniqueID() against CoreAudio's fixed built-in
    identifier is what actually finds the hardware."""
    if not IS_MAC:
        return None
    try:
        from AVFoundation import AVCaptureDeviceDiscoverySession, AVCaptureDeviceTypeMicrophone, AVMediaTypeAudio
        # AVCaptureDeviceDiscoverySession emits an ObjC-runtime NSLog warning
        # about deprecated Continuity Camera device types on every call, on
        # every macOS version this was tested on -- unrelated to audio, and
        # not something a Python try/except can catch since it's written
        # straight to the fd, not raised as an exception. Left alone, it
        # would print on every single flow.py invocation (this runs at
        # import time), reading as an error to anyone watching the log.
        # Silence just the fd for the duration of this one call.
        stderr_fd = sys.stderr.fileno()
        saved_fd = os.dup(stderr_fd)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, stderr_fd)
            session = AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
                [AVCaptureDeviceTypeMicrophone], AVMediaTypeAudio, 0  # AVCaptureDevicePositionUnspecified
            )
            devices = list(session.devices())
        finally:
            os.dup2(saved_fd, stderr_fd)
            os.close(saved_fd)
            os.close(devnull_fd)
        for device in devices:
            if str(device.uniqueID()) == _BUILTIN_MIC_UID:
                return str(device.localizedName())
        return None
    except Exception:
        return None
