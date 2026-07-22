"""Floating status pill for Wingvox on Windows. Same public contract as
overlay_mac.py -- StatusOverlay.show()/show_recording()/push_level()/hide(),
plus a module-level run_event_loop() -- so flow.py can dispatch between the
two without any other code changes.

Two visual regressions vs. the Mac version, both fundamental Tkinter/Win32
limits rather than bugs to chase: stock Tkinter's only transparency
mechanism on Windows is a colorkey ("-transparentcolor"), not a real alpha
channel, so the dark translucent capsule the Mac version draws renders here
as a fully opaque capsule; and Canvas has no native corner-radius primitive,
so rounded corners are hand-drawn and slightly less crisp than AppKit's
CALayer.cornerRadius. Click-through, unlike those two, is NOT approximated --
it's a real Win32 extended window style (WS_EX_TRANSPARENT).

Tkinter is not thread-safe -- every widget touch must happen on the thread
that called mainloop(). The pipeline runs on background threads, so all of
them (except push_level(), which just sets a plain attribute like
overlay_mac's pushRawLevel_) hand off through a queue.Queue drained by a
self-rescheduling root.after() poll on the main thread.
"""

import ctypes
import math
import queue
import threading
import tkinter as tk

PANEL_W, PANEL_H = 460, 40
WAVE_PANEL_W, WAVE_PANEL_H = 60, 26
WAVE_MARGIN = 3

COLORS = {
    "red": "#ff5c5c",
    "white": "#f2f2f2",
    "green": "#59d973",
    "orange": "#ffa640",
    "gray": "#b3b3b3",
}
BG_CAPSULE = "#141414"        # opaque stand-in for the Mac version's translucent black
TRANSPARENT_KEY = "#010203"   # colorkey -- must never appear in any drawn shape

WAVE_TICK_MS = 50  # ~20Hz, matches overlay_mac's WAVE_TICK_HZ
WAVE_LEVEL_GAIN = 55.0
NOISE_GATE = 0.4
MAX_AMPLITUDE_THRESHOLD = 0.55
WAVE_LINE_COUNT = 6
WAVE_LINE_WIDTH = 1
WAVE_COMPONENTS = [(1.6, 0.55), (3.1, 0.30), (5.0, 0.15)]

_active_overlay = None


def _monitor_rect_under_cursor():
    """(left, top, right, bottom) of the monitor containing the cursor, in
    Win32 screen coordinates (origin top-left)."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    user32 = ctypes.windll.user32
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    MONITOR_DEFAULTTONEAREST = 2
    hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcMonitor
    return r.left, r.top, r.right, r.bottom


def _rect_for(w, h):
    left, top, right, bottom = _monitor_rect_under_cursor()
    x = left + ((right - left) - w) // 2
    # Win32 is top-left origin, unlike Cocoa's bottom-left (where the Mac
    # version's "y = origin.y + 80" means 80px up from the bottom) -- so
    # "80px up from the bottom" here is bottom minus 80 minus the panel
    # height, not a literal +80.
    y = bottom - 80 - h
    return x, y


def _make_click_through(root):
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    )


def _rounded_rect(canvas, x0, y0, x1, y1, radius, **kwargs):
    """Canvas has no native corner-radius primitive -- approximate with a
    smoothed polygon whose corners are cut by `radius`."""
    points = [
        x0 + radius, y0, x1 - radius, y0, x1, y0, x1, y0 + radius,
        x1, y1 - radius, x1, y1, x1 - radius, y1, x0 + radius, y1,
        x0, y1, x0, y1 - radius, x0, y0 + radius, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class StatusOverlay:
    """Thread-safe handle to the pill. Create once, on the main thread,
    before run_event_loop() starts the mainloop -- then call
    show()/show_recording()/push_level()/hide() from any thread."""

    def __init__(self):
        global _active_overlay
        self._q = queue.Queue()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._peak = 0.0       # written directly by push_level() from the
        self._smoothed = 0.0   # audio callback thread, no queue hop --
        self._phase = 0.0      # same as overlay_mac's pushRawLevel_/tick_.
        self._recording = False

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.withdraw()  # start hidden until the first show()/show_recording()

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg=TRANSPARENT_KEY)
        self.canvas.pack(fill="both", expand=True)

        _make_click_through(self.root)
        self.root.after(WAVE_TICK_MS, self._pump)
        _active_overlay = self

    # ---------- public, thread-safe API ----------

    def show(self, text, color="white", hide_after=None):
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        self._q.put(("show", text, color, hide_after, seq))

    def show_recording(self):
        with self._seq_lock:
            self._seq += 1
        self._q.put(("show_recording",))

    def push_level(self, rms):
        if rms > self._peak:
            self._peak = rms

    def hide(self):
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        self._q.put(("hide", seq))

    # ---------- main-thread only, from here down ----------

    def _pump(self):
        # Runs on the Tk main thread via root.after -- the only thread
        # allowed to touch Tk widgets. Also the ~20Hz tick that redraws the
        # waveform while recording, and (as a side effect of re-entering
        # Python every 50ms) what keeps Ctrl+C responsive -- don't stretch
        # this interval out without checking that still holds.
        try:
            while True:
                self._handle(self._q.get_nowait())
        except queue.Empty:
            pass
        if self._recording:
            self._tick_waveform()
        self.root.after(WAVE_TICK_MS, self._pump)

    def _handle(self, cmd):
        kind = cmd[0]
        if kind == "show":
            _, text, color, hide_after, seq = cmd
            self._recording = False
            self._draw_status(text, color)
            if hide_after is not None:
                self.root.after(int(hide_after * 1000), lambda: self._hide_if_current(seq))
        elif kind == "show_recording":
            self._recording = True
            self._peak = 0.0
            self._smoothed = 0.0
            self._phase = 0.0
            self._draw_recording_frame()
        elif kind == "hide":
            self._hide_if_current(cmd[1])

    def _hide_if_current(self, seq):
        with self._seq_lock:
            if seq != self._seq:
                return  # a newer message already superseded this one
        self._recording = False
        self.root.withdraw()

    def _position(self, w, h):
        x, y = _rect_for(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _draw_status(self, text, color):
        self._position(PANEL_W, PANEL_H)
        self.canvas.delete("all")
        _rounded_rect(self.canvas, 0, 0, PANEL_W, PANEL_H, PANEL_H // 2, fill=BG_CAPSULE, outline="")
        self.canvas.create_text(
            PANEL_W // 2, PANEL_H // 2, text=text,
            fill=COLORS.get(color, COLORS["white"]),
            font=("Segoe UI", 11), anchor="c",
        )
        self.root.deiconify()

    def _draw_recording_frame(self):
        self._position(WAVE_PANEL_W, WAVE_PANEL_H)
        self.canvas.delete("all")
        _rounded_rect(self.canvas, 0, 0, WAVE_PANEL_W, WAVE_PANEL_H,
                      WAVE_PANEL_H // 2, fill="black", outline="")
        self.root.deiconify()

    def _tick_waveform(self):
        lvl = min(1.0, (self._peak * WAVE_LEVEL_GAIN) ** 0.5)
        self._peak = 0.0
        lvl = max(0.0, (lvl - NOISE_GATE) / (1.0 - NOISE_GATE))
        if lvl > self._smoothed:
            self._smoothed = self._smoothed * 0.3 + lvl * 0.7   # fast attack
        else:
            self._smoothed = self._smoothed * 0.75 + lvl * 0.25  # slow release
        amp = min(1.0, self._smoothed / MAX_AMPLITUDE_THRESHOLD)
        self._phase += 0.05 + amp * 0.22

        self.canvas.delete("wave")
        w = WAVE_PANEL_W - WAVE_MARGIN * 2
        h = WAVE_PANEL_H - WAVE_MARGIN * 2
        cy = WAVE_MARGIN + h / 2.0
        max_amp = h * 0.48
        line_amp_base = amp * max_amp
        steps = 40
        for i in range(WAVE_LINE_COUNT):
            line_amp = line_amp_base * (1.0 - i * 0.1)
            phase_off = i * 0.55
            pts = []
            for s in range(steps + 1):
                t = s / steps
                x = WAVE_MARGIN + w * t
                envelope = math.sin(math.pi * t)
                y = cy + line_amp * envelope * sum(
                    weight * math.sin(2 * math.pi * freq * t + self._phase + phase_off)
                    for freq, weight in WAVE_COMPONENTS
                )
                pts.extend((x, y))
            self.canvas.create_line(*pts, fill="white", width=WAVE_LINE_WIDTH, tags="wave")


def run_event_loop():
    """Blocks running the Tk mainloop on the main thread. Ctrl+C exits."""
    if _active_overlay is None:
        return
    try:
        _active_overlay.root.mainloop()
    except KeyboardInterrupt:
        pass
