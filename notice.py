"""Version-stamped notices that the user has to acknowledge once.

The channel for telling existing users something they need to know -- a
privacy disclaimer, a behavior change, anything that shouldn't just appear
silently in a git pull. NOTICE.md carries a version number; the version the
user last agreed to is recorded next to their dictionary. When the file's
version is higher than the recorded one, Wingvox asks before it starts
listening for the hotkey.

Bumping the version is what re-prompts everyone. Editing the body without
bumping it changes the text for new users only, which is usually the wrong
thing and always the quiet thing.
"""

import re
import subprocess
import sys

import platform_compat as pc

NOTICE_PATH = pc.install_dir() / "NOTICE.md"
AGREED_PATH = pc.data_dir() / "notice_agreed"

_VERSION_RE = re.compile(r"<!--\s*notice-version:\s*(\d+)\s*-->")


def parse_notice():
    """(version, title, body) from NOTICE.md, or None if there isn't a
    usable one. A missing or malformed file is not an error: it means this
    install has nothing to say, and Wingvox should start normally."""
    try:
        raw = NOTICE_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _VERSION_RE.search(raw)
    if not m:
        return None
    version = int(m.group(1))
    rest = _VERSION_RE.sub("", raw, count=1).strip()
    lines = rest.splitlines()
    title = "Wingvox"
    if lines and lines[0].startswith("#"):
        title = lines[0].lstrip("#").strip()
        lines = lines[1:]
    body = "\n".join(lines).strip()
    # The dialog renders plain text, so strip the markdown emphasis markers
    # rather than showing people literal asterisks.
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    return version, title, body


def agreed_version() -> int:
    try:
        return int(AGREED_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def record_agreement(version: int) -> None:
    try:
        AGREED_PATH.write_text(f"{version}\n", encoding="utf-8")
    except OSError as e:
        # Worth surfacing: if this can't be written the user gets re-asked on
        # every single launch, which looks broken rather than careful.
        print(f"  ⚠ couldn't record notice agreement ({e}) — it will ask again next start")


def pending():
    """The notice the user still needs to see, or None."""
    parsed = parse_notice()
    if parsed is None:
        return None
    version, title, body = parsed
    if version <= agreed_version():
        return None
    return version, title, body


# ---------- the dialog ----------

def _prompt_mac(title: str, body: str) -> bool:
    """NSAlert on the main thread. Returns whether they agreed.

    Called before the AppKit event loop starts, so runModal() spins its own
    -- sharedApplication() is a singleton, creating it here doesn't conflict
    with run_event_loop() creating it again later. Activation is explicit
    because Wingvox is LSUIElement: without it the alert can open behind
    whatever the user is looking at, and a modal you can't see reads as a
    hang.

    The body goes in a fixed-size accessoryView, not informativeText.
    informativeText auto-sizes the whole panel to its content *after* the
    first paint -- with text this long that's a visible resize a moment
    after the alert appears, which reads as one dialog being replaced by a
    different, differently-sized one (caught by the user during testing:
    the notice looked cut off, like a second box had swapped in for the
    first). A fixed-frame scroll view has nothing to recalculate, so it
    just appears once, correctly sized, with a scrollbar if the text
    outgrows it rather than a layout jump.
    """
    from AppKit import (NSAlert, NSApplication, NSApplicationActivationPolicyAccessory,
                        NSAlertFirstButtonReturn, NSScrollView, NSTextView,
                        NSMakeRect, NSFont)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)

    width, height = 420, 220
    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    text_view.setString_(body)
    text_view.setEditable_(False)
    text_view.setSelectable_(True)
    text_view.setFont_(NSFont.systemFontOfSize_(13))
    text_view.setVerticallyResizable_(True)
    text_view.setHorizontallyResizable_(False)
    text_view.setAutoresizingMask_(1 << 1)  # width tracks the scroll view

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    scroll.setDocumentView_(text_view)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(1)  # NSBezelBorder -- makes the fixed frame visually obvious
    alert.setAccessoryView_(scroll)

    alert.addButtonWithTitle_("Agree and continue")
    alert.addButtonWithTitle_("Quit")
    app.activateIgnoringOtherApps_(True)
    return alert.runModal() == NSAlertFirstButtonReturn


def _prompt_windows(title: str, body: str) -> bool:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return bool(messagebox.askokcancel(title, body, parent=root))
    finally:
        root.destroy()


def prompt(title: str, body: str):
    """True agreed, False declined, None the dialog couldn't be shown.

    The three-way return is the point. Collapsing "couldn't ask" into
    "declined" would mean a broken window server or a headless run silently
    turns Wingvox into an app that quits on startup.
    """
    try:
        return _prompt_mac(title, body) if pc.IS_MAC else _prompt_windows(title, body)
    except Exception as e:
        # No window server, a broken pyobjc, a headless test run. The
        # agreement isn't recorded, so it asks again next start, when the GUI
        # may well be back.
        print(f"  ⚠ couldn't show the notice dialog ({e}) — printing it instead")
        print()
        print(f"  {title}")
        print()
        for line in body.splitlines():
            print(f"  {line}")
        print()
        return None


def check(status=None) -> bool:
    """Show any pending notice and record the answer.

    Returns False only when the user actively declined -- the caller should
    exit. True means there was nothing to show, they agreed, or the dialog
    couldn't be shown at all.
    """
    p = pending()
    if p is None:
        return True
    version, title, body = p
    print(f"  Showing notice v{version} — waiting for the user")
    answer = prompt(title, body)
    if answer is None:
        print("  Notice shown in the log only — continuing without an answer")
        return True
    if answer:
        record_agreement(version)
        print(f"  Notice v{version} agreed")
        if status:
            status("✓ Thanks — Wingvox is ready", "green", hide_after=4)
        return True
    print("  Notice declined — exiting")
    return False


if __name__ == "__main__":
    # `python notice.py [--force]` -- inspect or exercise the dialog without
    # launching the whole app.
    if "--force" in sys.argv:
        parsed = parse_notice()
        if parsed is None:
            sys.exit("No usable NOTICE.md")
        v, t, b = parsed
        print(f"Showing v{v} regardless of what's already agreed…")
        print("agreed" if prompt(t, b) else "declined")
    else:
        parsed = parse_notice()
        print(f"NOTICE.md:      {NOTICE_PATH}")
        print(f"parsed:         {'v%d — %s' % (parsed[0], parsed[1]) if parsed else 'none'}")
        print(f"agreed file:    {AGREED_PATH}")
        print(f"agreed version: {agreed_version()}")
        print(f"pending:        {'yes' if pending() else 'no'}")
