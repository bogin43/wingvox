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

# The STT backend (mlx vs faster-whisper) and some install-time decisions
# depend on Mac architecture, not just "is this a Mac".
IS_ARM_MAC = IS_MAC and platform.machine() == "arm64"
IS_INTEL_MAC = IS_MAC and platform.machine() == "x86_64"

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


def key_vk(key):
    """VK code for a pynput Key enum member or KeyCode instance, or None if
    it can't be determined. A Key enum member doesn't expose vk directly --
    it has to go through .value (its underlying KeyCode) first; a bare
    KeyCode (an arbitrary letter/digit/symbol the hotkey picker captured)
    already carries .vk itself. pynput uses "vk" as the field name on both
    Windows (a real Win32 virtual-key code) and macOS (Apple's virtual
    keycode) -- different numbering systems, but this function doesn't need
    to reconcile them: a captured key is only ever compared against others
    captured on the same OS."""
    value = key.value if isinstance(key, keyboard.Key) else key
    return getattr(value, "vk", None)


def hotkey_keys_for(key):
    """Expands one configured hotkey (from hotkey_picker or a loaded
    hotkey.txt) into the tuple on_press/on_release check membership
    against. Needed because a single captured key can under-match: on
    Windows, physical Right Alt can report as alt_r or alt_gr depending on
    keyboard layout/driver (see the original HOTKEY_KEYS default below) --
    a picker or loaded file that only ever compares against the literal
    key it captured would silently lock out whichever of the two didn't
    happen to fire that time."""
    if IS_WINDOWS and key in (keyboard.Key.alt_r, keyboard.Key.alt_gr):
        return (keyboard.Key.alt_r, keyboard.Key.alt_gr)
    return (key,)


_KEY_LABELS = {
    keyboard.Key.alt_r: "Right Alt", keyboard.Key.alt_l: "Left Alt",
    keyboard.Key.alt_gr: "Right Alt", keyboard.Key.ctrl_r: "Right Ctrl",
    keyboard.Key.ctrl_l: "Left Ctrl", keyboard.Key.shift_r: "Right Shift",
    keyboard.Key.shift_l: "Left Shift", keyboard.Key.cmd: "Command",
    keyboard.Key.cmd_r: "Right Command", keyboard.Key.space: "Space",
    keyboard.Key.tab: "Tab", keyboard.Key.caps_lock: "Caps Lock",
}


def key_label(key) -> str:
    """Human-readable label for an arbitrary configured hotkey, for status
    messages ("tap {label} to dictate"). Mac's "Option" wording for
    alt_l/alt_r (MAC_HOTKEY_LABELS) is deliberately not handled here --
    that's layered on by the caller, since this function stays
    platform-neutral for every other key."""
    if isinstance(key, keyboard.Key):
        return _KEY_LABELS.get(key, key.name.replace("_", " ").title())
    if key.char:
        return key.char.upper()
    return f"key #{key.vk}" if key.vk is not None else "Unknown key"


if IS_WINDOWS:
    import ctypes
    VK_LMENU = 0xA4
    VK_RMENU = 0xA5

    # Raw WH_KEYBOARD_LL hook message constants, as handed to pynput's
    # win32_event_filter via Listener._convert()/_handler() -- duplicated
    # here rather than reaching into pynput's private Listener._WM_* class
    # attributes (not part of its public API). See
    # make_alt_suppressing_event_filter() below for why these matter.
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
    _PRESS_MESSAGES = (WM_KEYDOWN, WM_SYSKEYDOWN)
    _RELEASE_MESSAGES = (WM_KEYUP, WM_SYSKEYUP)

    def is_alt_family_vk(vk) -> bool:
        """Whether vk is Left or Right Alt -- the two physical keys whose
        bare tap+release trips Windows' menu-access-mode reflex
        (GUI_INMENUMODE), which silently swallows a Ctrl+V that lands while
        the focused window is still in that state. Confirmed by live
        reproduction: SendInput a solitary Right-Alt hold+release into a
        real window, GetGUIThreadInfo reports GUI_INMENUMODE set
        afterward, and a following Ctrl+V doesn't land. Generic over
        whichever key the user actually configured as the hotkey, not
        hardcoded to Right Alt -- a non-Alt hotkey (Right Ctrl, a letter,
        ...) needs none of this."""
        return vk in (VK_LMENU, VK_RMENU)

    def make_alt_suppressing_event_filter(hotkey_vk, guarded_on_press, guarded_on_release, get_listener):
        """Builds the win32_event_filter for pynput's Listener that stops a
        bare Alt-family hotkey from ever reaching GUI_INMENUMODE. Only
        meaningful when is_alt_family_vk(hotkey_vk) is True -- callers must
        skip installing this filter otherwise.

        Why the recording state machine has to run *inside* this filter,
        not a separate on_press/on_release pair: pynput's
        Listener._convert() -- which is what invokes this filter -- runs
        BEFORE the matching press/release message is posted to pynput's
        own dispatch queue. Calling listener.suppress_event() from a
        separate on_press/on_release callback (a previously abandoned
        attempt) raises SystemHook.SuppressException from inside
        _convert() itself, which unwinds before that queue-post ever
        happens -- on_press/on_release then silently never fire for that
        event at all, indistinguishable from the hotkey being dead
        (confirmed by reading pynput's installed
        keyboard/_win32.py + _util/win32.py). Running the same guarded
        on_press/on_release closures directly from here, then suppressing
        only after, sidesteps that: this sees the raw event first, drives
        the state machine itself, and only then blocks the event from
        ever reaching the OS's own default menu-mode handling.

        A solitary Right Alt's key-up arrives as plain WM_KEYUP, not
        WM_SYSKEYUP like every other Alt release -- confirmed via the same
        live repro above. Matched across all four message types (not just
        the SYS-prefixed ones) so that release isn't missed.

        get_listener: a zero-arg callable returning the Listener instance
        once constructed. The filter is passed in as a Listener()
        constructor kwarg, so the Listener doesn't exist yet when this
        closure is built -- by the time the filter itself actually runs,
        listener.start() has already returned and the name is bound."""
        alt_key = keyboard.Key.alt_r if hotkey_vk == VK_RMENU else keyboard.Key.alt_l

        def _filter(msg, data):
            if data.vkCode != hotkey_vk:
                return True  # not the hotkey -- dispatch normally
            if msg in _PRESS_MESSAGES:
                guarded_on_press(alt_key)
            elif msg in _RELEASE_MESSAGES:
                guarded_on_release(alt_key)
            else:
                return True
            get_listener().suppress_event()  # raises; never returns
        return _filter

    def is_hotkey_physically_down(key) -> bool:
        """Whether the dictation key is physically held right now, read from
        the hardware rather than from the keyboard hook.

        The hook has been observed to silently drop the release event for
        the dictation key (seen under UTM VM keyboard passthrough): the
        press fires, the matching release never does, and the recording
        stays open forever. Callers poll this as a backstop.

        key is whatever the user configured (via hotkey_picker or a loaded
        hotkey.txt) -- resolved to a VK via key_vk() so this works for any
        hotkey, not just the original hardcoded Right Alt."""
        vk = key_vk(key)
        if vk is None:
            return True  # can't determine -- fail open, same as the Mac branch below
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
elif IS_MAC:
    def is_hotkey_physically_down(key) -> bool:
        """Mac counterpart of the Windows check above. Same purpose: a
        dropped release must not be able to wedge a recording open, and a
        wedged recording can only be cleared by restarting the app."""
        vk = key_vk(key)
        if vk is None:
            return True
        try:
            from Quartz import CGEventSourceKeyState, kCGEventSourceStateHIDSystemState
            return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, vk))
        except Exception:
            # Can't read the hardware -- claim the key is still down so the
            # watchdog never ends a recording the user is in the middle of.
            return True
else:
    def is_hotkey_physically_down(_key=None) -> bool:
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


def _text_before_cursor_windows(max_chars: int):
    """Windows counterpart of the Mac implementation below, via UI
    Automation instead of the Accessibility API. Same contract: None means
    "couldn't determine", never "empty field".

    Two paths, tried in order:

    1. TextPattern, for controls rich enough to expose it (Chrome/Electron
       contenteditable, WordPad, Word). Moves only the caret range's Start
       endpoint backward by max_chars characters rather than reading
       DocumentRange (the whole field/document) and slicing in Python --
       matters on a field holding a large document, where fetching the
       entire text on every dictation would be needless latency for a
       value only the last couple hundred characters of which are ever
       used.

    2. A classic Win32 EM_GETSEL message, for plain Edit/RichEdit controls
       that don't support TextPattern at all -- confirmed directly against
       real Notepad, whose text box exposes ValuePattern and
       LegacyIAccessiblePattern but returns None for every TextPattern
       variant. Gated on ValuePattern actually being present (an
       affirmative "this is a text-bearing control" signal) so a control
       that answers neither path isn't guessed at with an arbitrary
       message send."""
    try:
        import uiautomation as auto
        control = auto.GetFocusedControl()
        if control is None:
            return None
        text_pattern = control.GetPattern(auto.PatternId.TextPattern)
        if text_pattern is not None:
            selection = text_pattern.GetSelection()
            if not selection:
                return None
            before = selection[0].Clone()
            # waitTime=0: uiautomation's default is an unconditional 0.5s
            # sleep *after every call*, regardless of success -- confirmed
            # by reading its source. Left at its default, this would add
            # half a second of latency to every dictation that reaches
            # this path, on a push-to-talk tool where perceived latency is
            # exactly what WHISPER_MODEL's beam_size=1 (see stt_windows.py)
            # exists to avoid.
            before.MoveEndpointByUnit(
                auto.TextPatternRangeEndpoint.Start, auto.TextUnit.Character,
                -max_chars, waitTime=0,
            )
            return before.GetText(-1)

        value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
        hwnd = control.NativeWindowHandle
        if value_pattern is None or not hwnd:
            return None
        text = value_pattern.Value
        if not isinstance(text, str):
            return None
        EM_GETSEL = 0x00B0
        start = ctypes.c_uint()
        end = ctypes.c_uint()
        ctypes.windll.user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
        return text[:start.value][-max_chars:]
    except Exception:
        return None


def text_before_cursor(max_chars: int = 200):
    """Best-effort read of the text immediately before the caret in
    whatever text field is currently focused -- via the Accessibility API
    on Mac, UI Automation's TextPattern on Windows.

    Lets flow.py's process() decide whether a dictation is starting a
    fresh sentence or continuing an unfinished one, and whether a space
    needs to go in before it, from what's actually in the field instead
    of guessing from Wingvox's own dictation history. On Mac this is a
    more sensitive use of the same Accessibility trust already granted for
    the paste keystroke (has_accessibility_access() above): it reads
    nearby field text, not just simulates a key press.

    Returns None whenever this can't be determined -- no focused element,
    the focused control doesn't expose text attributes (some Electron/
    canvas-based editors don't, on either platform), or anything else goes
    wrong. Callers must treat None as "unknown, fall back to your own
    heuristic", not as "empty field" -- a false "empty" would wrongly skip
    a needed space or wrongly capitalize a continuation."""
    if IS_WINDOWS:
        return _text_before_cursor_windows(max_chars)
    if not IS_MAC:
        return None
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue, AXValueGetValue,
            kAXFocusedUIElementAttribute, kAXFocusedWindowAttribute,
            kAXValueAttribute, kAXSelectedTextRangeAttribute,
            kAXValueCFRangeType, kAXWindowsAttribute,
        )

        def read_text_and_caret(element):
            err, value = AXUIElementCopyAttributeValue(element, kAXValueAttribute, None)
            if err or not isinstance(value, str):
                return None
            err, rng = AXUIElementCopyAttributeValue(
                element, kAXSelectedTextRangeAttribute, None)
            if err or rng is None:
                return None
            ok, cfrange = AXValueGetValue(rng, kAXValueCFRangeType, None)
            if not ok:
                return None
            location = cfrange[0]
            return value, location

        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None)
        if err or focused is None:
            # The system-wide element occasionally can't resolve this
            # directly (observed during testing). Asking the frontmost
            # app for its own focused element, rather than going through
            # the system-wide proxy, is the more reliable path.
            try:
                from AppKit import NSWorkspace
                pid = NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
                app = AXUIElementCreateApplication(pid)
                err, focused = AXUIElementCopyAttributeValue(
                    app, kAXFocusedUIElementAttribute, None)
                if err or focused is None:
                    # Chromium (Chrome, Electron apps) builds its
                    # accessibility tree lazily and won't answer even this
                    # basic a query until something has asked it for more
                    # than just the focused element -- confirmed by testing
                    # against real Chrome. Asking for its windows is enough
                    # to make it turn the tree on; the result isn't used,
                    # only the side effect of having asked. Once triggered
                    # this way it stays on for the rest of that app's run,
                    # so this retry only actually does anything the first
                    # time Wingvox meets a given Chromium app process.
                    AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, None)
                    err, focused = AXUIElementCopyAttributeValue(
                        app, kAXFocusedUIElementAttribute, None)
            except Exception:
                focused = None
            if err or focused is None:
                return None

        result = read_text_and_caret(focused)
        if result is None:
            # The focused element found above is sometimes a container
            # (e.g. the window) rather than the text view actually
            # holding the caret -- observed on a real app during testing.
            # Try one level down before giving up.
            err, window = AXUIElementCopyAttributeValue(
                focused, kAXFocusedWindowAttribute, None)
            if not err and window is not None:
                err, deeper = AXUIElementCopyAttributeValue(
                    window, kAXFocusedUIElementAttribute, None)
                if not err and deeper is not None:
                    result = read_text_and_caret(deeper)
        if result is None:
            return None

        text, caret = result
        return text[max(0, caret - max_chars):caret]
    except Exception:
        return None


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
        # pbcopy decodes its stdin using the subprocess's locale (LANG/
        # LC_CTYPE) -- launchd gives this LaunchAgent no locale at all, so
        # any non-ASCII character (the non-breaking space in inject(),
        # "…" before its ASCII-dots replacement below) got silently
        # mangled on the pasteboard, showing up as mojibake on paste.
        # AppKit's NSPasteboard takes the string directly, no byte/locale
        # decoding step to get wrong -- same class already used to read
        # the clipboard in clipboard_get() above.
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            board = NSPasteboard.generalPasteboard()
            board.clearContents()
            board.setString_forType_(text, NSPasteboardTypeString)
            return
        except Exception:
            pass  # fall through to the subprocess path below
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
    the checkout, not at %LOCALAPPDATA%.

    Under a frozen PyInstaller build, __file__ resolves inside the
    extracted _internal directory (dist/Wingvox/_internal), not the actual
    checkout -- confirmed by testing: NOTICE_PATH (notice.py) silently
    never found NOTICE.md there, so the first-run privacy notice never
    appeared at all when running the real built .exe (the git-based update
    check happened to keep working anyway, purely by coincidence -- dist/
    sits inside the same repo, and `git -C` walks up looking for .git
    regardless of which subdirectory it's pointed at). wingvox.spec's
    COLLECT always places the exe at <repo>/dist/Wingvox/Wingvox.exe, so
    climb three levels from the running executable's own path instead of
    trusting __file__ when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent.parent
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
    the log and the docs can't drift apart -- historically they haven't:
    the status pill used to show a hardcoded, wrong instruction instead of
    calling this function, which is exactly the drift this centralization
    is meant to prevent."""
    if IS_MAC:
        return (f"cd {install_dir()} && git pull && "
                f"launchctl kickstart -k gui/$(id -u)/{LAUNCH_AGENT_LABEL}")
    # `git pull` alone is not enough on Windows the way it is on Mac: Mac
    # runs flow.py straight out of the checkout, so a pull takes effect on
    # restart with nothing else needed. Windows runs a compiled PyInstaller
    # exe in dist\Wingvox\ -- pulling new source leaves that exe untouched,
    # so a plain restart (wingvox-off.cmd/wingvox-on.cmd) keeps running the
    # OLD code while reporting itself up to date. update.ps1 does the pull
    # AND the rebuild AND the restart, in that order.
    return f"cd {install_dir()} && .\\update.ps1"


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


def _run_update_mac() -> str:
    script = install_dir() / "update.sh"
    if not script.exists():
        return "error:update.sh not found"
    try:
        r = subprocess.run(
            ["/bin/bash", str(script)],
            cwd=str(install_dir()),
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return "error:timed out (slow network?)"
    except Exception as e:
        return f"error:{e}"
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if line.startswith("WINGVOX_RESULT:"):
            return line[len("WINGVOX_RESULT:"):].strip()
    return f"error:no result marker (exit {r.returncode})"


def _run_update_windows() -> str:
    """Unlike Mac's synchronous update.sh run above, this can't wait for
    update.ps1 to finish and read its result: partway through, install.ps1
    (which update.ps1 hands off to) stops the running Wingvox.exe -- which
    is *this* process -- before it can rebuild the now-locked binary. A
    subprocess.run() call waiting on that would simply never return, because
    the process making the call is the one about to die. So the dirty/behind
    checks below run directly in Python first (cheap, and don't touch
    anything), and only the actual pull+rebuild+restart is handed off,
    fire-and-forget, the same way Mac's launchctl kickstart -k tears its own
    process down mid-update and lets a freshly-relaunched one take over.

    update.ps1 is triggered via the separate "Wingvox-Updater" scheduled
    task (install.ps1 registers it, trigger-less, run-on-demand only) rather
    than spawned directly as a child of this process. A direct child
    inherits this process's Task-Scheduler job, and update.ps1 stopping
    Wingvox.exe partway through would risk taking its own job-mate down
    with it. The obvious fix -- CREATE_BREAKAWAY_FROM_JOB -- turns out not
    to be available here: confirmed by reproduction that CreateProcess
    fails outright with WinError 5 (Access is denied) when asked to break
    away from Wingvox's own Task-Scheduler job on this configuration, so
    that flag can't be relied on. A separate top-level scheduled task has
    no parent/job relationship to Wingvox.exe at all -- stopping Wingvox
    can't affect it, no matter how Task Scheduler treats job membership on
    a given Windows version."""
    dirty = _git("status", "--short", "--untracked-files=no")
    if dirty:
        return "dirty"
    behind = check_for_update()
    if behind is None:
        return "error:couldn't check for an update (offline, or not a git checkout)"
    if behind is False:
        return "up_to_date"
    try:
        r = subprocess.run(
            ["schtasks", "/run", "/tn", "Wingvox-Updater"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        return f"error:{e}"
    if r.returncode != 0:
        reason = (r.stderr or r.stdout).strip() or f"exit {r.returncode}"
        return f"error:couldn't start the updater task ({reason})"
    return "updated"


def run_update() -> str:
    """Take a published update and report what happened: 'dirty',
    'up_to_date', 'needs_install' (Mac only -- see update.sh), 'updated', or
    'error:<reason>'. Meant to be called from a background thread: this
    function only ever blocks its caller, never raises, so the caller never
    needs to catch anything -- a timeout, a missing script, or unexpected
    output all fold into a plain 'error:...' string same as an actual
    failure would."""
    if IS_MAC:
        return _run_update_mac()
    if IS_WINDOWS:
        return _run_update_windows()
    return "error:not supported on this platform"


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


# Substrings Windows uses in a Bluetooth mic's device name -- seen in the
# wild as e.g. "Headset (Bluetooth Hands-Free AG Audio)" or "Bluetooth
# Hands-Free Audio". Not exhaustive (Windows has no stable, driver-independent
# "this is Bluetooth" flag the way CoreAudio's transport type does), but these
# two catch the labeling Windows itself generates for the HFP profile, which
# is what a Bluetooth headset's *microphone* shows up as -- its higher-quality
# A2DP profile is playback-only and never appears as an input device at all.
_BLUETOOTH_MIC_HINTS = ("bluetooth", "hands-free")


def default_windows_input_device(sd):
    """PortAudio's default host API on Windows is often MME (higher latency,
    occasionally flaky) rather than WASAPI. Return WASAPI's default input
    device index, or None (caller falls back to the system default).

    Also steers away from a Bluetooth headset mic when one is the current
    default: Bluetooth's HFP mic profile downgrades the *output* audio
    quality on every app system-wide for as long as it's in use (not just
    Wingvox's own recording), so a laptop's built-in mic is very likely the
    better choice whenever both are available. Unlike Mac (mac_builtin_mic_name
    above), there's no stable hardware identifier for "the built-in mic" on
    Windows to match against directly -- this looks for the opposite signal
    instead: any other WASAPI input device whose name doesn't look like a
    Bluetooth mic. Imperfect on a desktop with no built-in mic and only USB
    peripherals (it would just pick another arbitrary USB device), but that
    case has no default worth preferring over the OS's own choice anyway."""
    if not IS_WINDOWS:
        return None
    try:
        hostapis = sd.query_hostapis()
        wasapi_index = None
        for i, api in enumerate(hostapis):
            if "wasapi" in api["name"].lower():
                wasapi_index = i
                break
        if wasapi_index is None:
            return None
        default_device = hostapis[wasapi_index].get("default_input_device", -1)
        if default_device < 0:
            return None
        devices = sd.query_devices()
        default_name = devices[default_device]["name"].lower()
        if not any(hint in default_name for hint in _BLUETOOTH_MIC_HINTS):
            return default_device
        for i, d in enumerate(devices):
            if (d["max_input_channels"] > 0 and d["hostapi"] == wasapi_index
                    and not any(hint in d["name"].lower() for hint in _BLUETOOTH_MIC_HINTS)):
                return i
        return default_device  # no non-Bluetooth alternative found
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
