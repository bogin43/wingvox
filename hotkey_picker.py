"""Interactive "tap the key you'd like to use" hotkey picker.

Shown once on a genuine first run (see flow.py's load_hotkey()) and again
whenever `flow.py set-hotkey` is run by hand. Two phases per platform:
capture (a short-lived pynput Listener grabs the next key pressed anywhere)
then confirm (show what was captured, Confirm/Try again) -- so an accidental
tap doesn't silently become the new hotkey.

Deliberately its own module rather than folded into notice.py, even though
both show a first-run modal: notice.py's job is a fixed agree/decline
question, this one's is capture-then-confirm over an open-ended value. Kept
separate so neither grows into a general-purpose "first-run UI" grab-bag.
"""

import queue
import threading

from pynput import keyboard

import platform_compat as pc


def capture_key():
    """Blocks until the next key is pressed anywhere, then returns it (a
    pynput Key enum member or KeyCode). Runs its own short-lived Listener --
    the real hotkey listener doesn't exist yet this early in startup."""
    result = {}
    captured = threading.Event()
    listener = None

    def _on_press(key):
        if captured.is_set():
            # listener.stop() doesn't synchronously prevent an
            # already-queued repeat callback from also firing -- guard
            # against a second event overwriting the first capture.
            return
        captured.set()
        result["key"] = key
        listener.stop()

    listener = keyboard.Listener(on_press=_on_press)
    listener.start()
    listener.join()
    return result.get("key")


def _is_plain_char(key) -> bool:
    return not isinstance(key, keyboard.Key) and bool(key.char)


def _typing_warning(key) -> str:
    return (f"“{key.char}” is also used for normal typing — every press of "
            "it anywhere will start dictation while Wingvox is running.")


# ---------- Windows ----------

def _picker_windows():
    import tkinter as tk

    root = tk.Tk()
    root.title("Wingvox — Choose your hotkey")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("420x170")
    try:
        root.eval("tk::PlaceWindow . center")
    except Exception:
        pass  # cosmetic only -- an off-center window still works fine

    label = tk.Label(root, text="", font=("Segoe UI", 12), wraplength=380, justify="center")
    label.pack(pady=(28, 6))
    warn = tk.Label(root, text="", font=("Segoe UI", 9), fg="#a06000", wraplength=380, justify="center")
    warn.pack()
    btn_frame = tk.Frame(root)

    q = queue.Queue()
    result = {}

    def _start_capture():
        label.config(text="Tap the key you'd like to use to start dictation…")
        warn.config(text="")
        btn_frame.pack_forget()
        threading.Thread(target=lambda: q.put(capture_key()), daemon=True).start()

    def _poll():
        try:
            key = q.get_nowait()
        except queue.Empty:
            root.after(80, _poll)
            return
        result["key"] = key
        label.config(text=f"You tapped: {pc.key_label(key)}")
        warn.config(text=_typing_warning(key) if _is_plain_char(key) else "")
        btn_frame.pack(pady=(10, 16))

    def _confirm():
        root.destroy()

    def _retry():
        _start_capture()
        root.after(80, _poll)

    tk.Button(btn_frame, text="Confirm", width=10, command=_confirm).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Try again", width=10, command=_retry).pack(side="left", padx=6)

    # No cancel path by design -- a hotkey is required for Wingvox to run at
    # all, so closing this window would just leave the app unable to start.
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    _start_capture()
    root.after(80, _poll)
    root.mainloop()
    return result.get("key")


# ---------- macOS ----------

def _show_capture_panel_mac():
    """Non-activating NSPanel with a plain label, shown while capture_key()
    runs on its own thread. Deliberately simple (a real NSTextField, no
    custom hand-drawn buttons like overlay_mac.py's pill) -- confirm/retry
    happens via a real NSAlert afterward instead, once capture has already
    finished, so there's no button hit-testing to get right here."""
    from AppKit import (
        NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, NSStatusWindowLevel, NSColor, NSTextField,
        NSMakeRect, NSFont, NSScreen,
    )
    w, h = 420, 80
    screen = NSScreen.mainScreen().frame()
    x = screen.origin.x + (screen.size.width - w) / 2
    y = screen.origin.y + screen.size.height * 0.6
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, w, h),
        NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False,
    )
    panel.setLevel_(NSStatusWindowLevel)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.92))
    panel.setHidesOnDeactivate_(False)

    label = NSTextField.alloc().initWithFrame_(NSMakeRect(16, 20, w - 32, 40))
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(1)  # NSTextAlignmentCenter
    label.setFont_(NSFont.systemFontOfSize_(14))
    label.setTextColor_(NSColor.whiteColor())
    label.setStringValue_("Tap the key you'd like to use to start dictation…")
    panel.contentView().addSubview_(label)

    panel.orderFrontRegardless()
    return panel


def _confirm_mac(key) -> bool:
    """NSAlert asking to confirm or retry a captured key. Returns True to
    confirm, False to try again. Same AppKit NSAlert shape as notice.py's
    _prompt_mac, kept as a separate implementation rather than a shared
    helper -- confirm/retry isn't the same question as notice.py's
    agree/decline, and duplicating a few lines here is cheaper than adding
    a button-label parameter to notice.py just for this."""
    from AppKit import (
        NSAlert, NSApplication, NSApplicationActivationPolicyAccessory,
        NSAlertFirstButtonReturn,
    )
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Confirm your hotkey")
    body = f"You tapped: {pc.key_label(key)}"
    if _is_plain_char(key):
        body += "\n\n" + _typing_warning(key)
    alert.setInformativeText_(body)
    alert.addButtonWithTitle_("Confirm")
    alert.addButtonWithTitle_("Try again")
    app.activateIgnoringOtherApps_(True)
    return alert.runModal() == NSAlertFirstButtonReturn


def _picker_mac():
    while True:
        panel = _show_capture_panel_mac()
        key = capture_key()
        panel.close()
        if key is None:
            continue
        if _confirm_mac(key):
            return key


# ---------- entry point ----------

def run(status=None):
    """Blocks until the user has tapped and confirmed a hotkey. Returns a
    pynput Key enum member or KeyCode -- pass straight to flow.py's
    save_hotkey()."""
    if status:
        status("Choose your dictation hotkey…", "white")
    return _picker_mac() if pc.IS_MAC else _picker_windows()
