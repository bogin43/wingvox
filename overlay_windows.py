"""Floating status pill for Wingvox on Windows. Same public contract as
overlay_mac.py -- StatusOverlay.show()/show_recording()/push_level()/hide(),
plus a module-level run_event_loop() -- so flow.py can dispatch between the
two without any other code changes.

Each frame is rendered as an anti-aliased RGBA bitmap via Pillow --
supersampled at SCALE x, then downsampled with a LANCZOS filter, since
neither Tkinter's Canvas primitives nor GDI antialias anything on their
own -- and displayed through a real per-pixel-alpha layered window
(UpdateLayeredWindow) instead of Tkinter's colorkey trick
("-transparentcolor"). Colorkey transparency is strictly binary (a pixel
is either fully invisible or fully opaque), which is why an earlier version
of this file rendered the pill as a flat opaque capsule with hard, jagged
edges instead of Mac's soft translucent one -- a real per-pixel alpha
channel is the only way to blend smoothly against whatever's actually
behind the window on the desktop, the same as AppKit/Quartz does for
overlay_mac.py automatically.

The Tk root window still owns position (root.geometry(), same _rect_for()
math as before) and click-through toggling (WS_EX_TRANSPARENT). It no
longer owns visible rendering, though -- once UpdateLayeredWindow has been
called on a window, Windows stops delivering WM_PAINT for it and relies
entirely on the bitmap supplied there, so a Canvas child's own drawing
would never actually be shown. Mouse input delivery is unaffected by that,
so button clicks are hit-tested directly against stored screen rects from
a plain <Button-1> binding on the root instead.

Tkinter is not thread-safe -- every widget touch must happen on the thread
that called mainloop(). The pipeline runs on background threads, so all of
them (except push_level(), which just sets a plain attribute like
overlay_mac's pushRawLevel_) hand off through a queue.Queue drained by a
self-rescheduling root.after() poll on the main thread.
"""

import ctypes
import ctypes.wintypes as wintypes
import math
import queue
import threading
import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PANEL_W, PANEL_H = 460, 40
WAVE_PANEL_W, WAVE_PANEL_H = 60, 26
WAVE_MARGIN = 3

# Supersampling factor: each frame is drawn at (W*SCALE, H*SCALE) and
# downsampled with LANCZOS resampling, which is what actually produces the
# antialiased edges/text/lines -- draw-then-shrink, not any special flag on
# the drawing calls themselves (Pillow's ImageDraw has no antialiasing of
# its own at 1x). 4x measured as enough that individual samples are no
# longer visible on the rounded corners or the waveform strands at the
# pill's actual on-screen size, without costing enough CPU/time per frame
# to be visible at the waveform's ~20Hz tick rate.
SCALE = 4

COLORS = {
    "red": (255, 92, 92, 255),
    "white": (242, 242, 242, 255),
    "green": (89, 217, 115, 255),
    "orange": (255, 166, 64, 255),
    "gray": (179, 179, 179, 255),
}
BG_CAPSULE = (20, 20, 20, 224)  # ~0.88 alpha -- same translucent black as overlay_mac's
WAVE_BG = (0, 0, 0, 235)

BTN_H = 26
NOTNOW_W = 74
UPDATE_W = 66
BTN_GAP = 8
BTN_RIGHT_MARGIN = 14
NOTNOW_X0 = PANEL_W - BTN_RIGHT_MARGIN - NOTNOW_W
UPDATE_X0 = NOTNOW_X0 - BTN_GAP - UPDATE_W
BTN_Y0 = (PANEL_H - BTN_H) / 2.0
MSG_X = 16
MSG_W_INTERACTIVE = UPDATE_X0 - BTN_GAP - MSG_X
UPDATE_BG, UPDATE_FG = (76, 184, 107, 255), (255, 255, 255, 255)
NOTNOW_BG, NOTNOW_FG = (58, 58, 58, 255), (209, 209, 209, 255)

WAVE_TICK_MS = 50  # ~20Hz, matches overlay_mac's WAVE_TICK_HZ
WAVE_LEVEL_GAIN = 55.0
NOISE_GATE = 0.4
MAX_AMPLITUDE_THRESHOLD = 0.55
WAVE_LINE_COUNT = 6
WAVE_LINE_ALPHA = 140
WAVE_LINE_WIDTH = 2
WAVE_COMPONENTS = [(1.6, 0.55), (3.1, 0.30), (5.0, 0.15)]

TEXT_SIZE = 15      # ~ Segoe UI 11pt at 96 DPI
BTN_TEXT_SIZE = 14  # ~ Segoe UI 10pt at 96 DPI
_FONT_PATH = r"C:\Windows\Fonts\segoeui.ttf"
_font_cache = {}


def _font(size):
    """Cached PIL font handle at the given (already SCALE-multiplied) pixel
    size. Falls back to Pillow's bitmap default font on the rare machine
    missing Segoe UI outright -- ugly, but keeps the pill legible rather
    than raising and killing the overlay thread."""
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(_FONT_PATH, size)
        except OSError:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


_active_overlay = None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", ctypes.c_ulong)]


def _monitor_rect_under_cursor():
    """(left, top, right, bottom) of the monitor containing the cursor, in
    Win32 screen coordinates (origin top-left)."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    MONITOR_DEFAULTTONEAREST = 2
    hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
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


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    # bmiColors is unused (and never read by CreateDIBSection) for 32bpp
    # BI_RGB -- present only because BITMAPINFO's layout requires a color
    # table field to exist at all.
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


# Every one of these handle-bearing functions needs an explicit argtypes/
# restype: ctypes' default marshaling for an undeclared foreign function
# assumes a 32-bit C int, and a GDI/window handle on 64-bit Windows is a
# full pointer-sized value that can exceed that range. Left undeclared,
# this doesn't fail reliably -- it depends on whether a given handle's
# numeric value happens to fit in 32 bits, which varies by process and
# handle-table state -- confirmed by a real crash in production
# (ctypes.ArgumentError: OverflowError on CreateCompatibleDC) that never
# reproduced in local testing before it shipped. c_void_p is used uniformly
# for every handle type (HDC, HBITMAP, the generic HGDIOBJ SelectObject
# takes/returns) rather than picking out the exact wintypes name for each,
# since all of them are equally just opaque pointer-sized values to ctypes.
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
    ctypes.c_void_p, ctypes.POINTER(_POINT), wintypes.COLORREF,
    ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL


def _make_click_through(root):
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id())
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
    return hwnd


def _set_click_through(hwnd, enabled: bool) -> None:
    """Toggles WS_EX_TRANSPARENT on the already-layered window -- used to let
    clicks land on the Update/Not-now buttons while the pill is showing them,
    without giving up click-through the rest of the time (Mac's equivalent is
    panel.setIgnoresMouseEvents_ in overlay_mac.py). Independent of
    UpdateLayeredWindow/ULW_ALPHA, which only controls the window's
    appearance -- input delivery is governed by this style bit alone."""
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def _premultiplied_bgra_bytes(img: Image.Image) -> bytes:
    """RGBA PIL image -> premultiplied-alpha BGRA bytes, top-down row order
    -- the exact pixel format UpdateLayeredWindow's ULW_ALPHA blend mode
    requires (AC_SRC_ALPHA expects each color channel already multiplied by
    its own alpha, not straight/unassociated alpha)."""
    arr = np.asarray(img, dtype=np.uint16)  # H, W, 4 (RGBA)
    alpha = arr[:, :, 3:4]
    premultiplied_rgb = (arr[:, :, :3] * alpha // 255).astype(np.uint8)
    bgra = np.dstack([
        premultiplied_rgb[:, :, 2], premultiplied_rgb[:, :, 1], premultiplied_rgb[:, :, 0],
        arr[:, :, 3].astype(np.uint8),
    ])
    return np.ascontiguousarray(bgra).tobytes()


def _push_layered_frame(hwnd, img: Image.Image) -> None:
    """Displays img (RGBA) as hwnd's entire visible appearance. hwnd must
    already have WS_EX_LAYERED set (done once in _make_click_through)."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    pixel_bytes = _premultiplied_bgra_bytes(img)

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # negative = top-down DIB, matching our row order
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    ppv_bits = ctypes.c_void_p()
    hbitmap = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(ppv_bits), None, 0)
    old_bitmap = gdi32.SelectObject(hdc_mem, hbitmap)
    try:
        ctypes.memmove(ppv_bits, pixel_bytes, len(pixel_bytes))

        size = _SIZE(w, h)
        pt_src = _POINT(0, 0)
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        # pptDst=None: leave the window at whatever position Tkinter's own
        # root.geometry() already placed it at, rather than repositioning
        # it here too -- one source of truth for position, same as before.
        user32.UpdateLayeredWindow(
            hwnd, hdc_screen, None, ctypes.byref(size),
            hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA,
        )
    finally:
        gdi32.SelectObject(hdc_mem, old_bitmap)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)


def _rounded_rect(draw, x0, y0, x1, y1, radius, fill):
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _render_status(text, color, interactive) -> Image.Image:
    s = SCALE
    w, h = PANEL_W * s, PANEL_H * s
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, 0, 0, w - 1, h - 1, h // 2, BG_CAPSULE)
    fg = COLORS.get(color, COLORS["white"])
    if interactive:
        draw.text((MSG_X * s, h / 2), text, font=_font(TEXT_SIZE * s), fill=fg, anchor="lm")
        for x0, bw, label, bg, btn_fg in (
            (UPDATE_X0, UPDATE_W, "Update", UPDATE_BG, UPDATE_FG),
            (NOTNOW_X0, NOTNOW_W, "Not now", NOTNOW_BG, NOTNOW_FG),
        ):
            by0 = BTN_Y0 * s
            bx0, bx1, by1 = x0 * s, (x0 + bw) * s, by0 + BTN_H * s
            _rounded_rect(draw, bx0, by0, bx1, by1, BTN_H * s // 2, bg)
            draw.text(((bx0 + bx1) / 2, (by0 + by1) / 2), label,
                      font=_font(BTN_TEXT_SIZE * s), fill=btn_fg, anchor="mm")
    else:
        draw.text((w / 2, h / 2), text, font=_font(TEXT_SIZE * s), fill=fg, anchor="mm")
    return img.resize((PANEL_W, PANEL_H), Image.LANCZOS)


def _render_wave_background() -> Image.Image:
    s = SCALE
    w, h = WAVE_PANEL_W * s, WAVE_PANEL_H * s
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, 0, 0, w - 1, h - 1, h // 2, WAVE_BG)
    return img


def _render_wave_frame(bg: Image.Image, amp: float, phase: float) -> Image.Image:
    s = SCALE
    img = bg.copy()
    draw = ImageDraw.Draw(img)
    ww = (WAVE_PANEL_W - WAVE_MARGIN * 2) * s
    hh = (WAVE_PANEL_H - WAVE_MARGIN * 2) * s
    margin = WAVE_MARGIN * s
    cy = margin + hh / 2.0
    max_amp = hh * 0.48
    line_amp_base = amp * max_amp
    steps = 90
    for i in range(WAVE_LINE_COUNT):
        line_amp = line_amp_base * (1.0 - i * 0.1)
        phase_off = i * 0.55
        pts = []
        for step in range(steps + 1):
            t = step / steps
            x = margin + ww * t
            envelope = math.sin(math.pi * t)
            y = cy + line_amp * envelope * sum(
                weight * math.sin(2 * math.pi * freq * t + phase + phase_off)
                for freq, weight in WAVE_COMPONENTS
            )
            pts.append((x, y))
        draw.line(pts, fill=(255, 255, 255, WAVE_LINE_ALPHA), width=WAVE_LINE_WIDTH * s // 2, joint="curve")
    return img.resize((WAVE_PANEL_W, WAVE_PANEL_H), Image.LANCZOS)


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
        self._on_click = None  # armed only while showing an interactive state
        self._update_btn_rect = None   # (x0, y0, x1, y1) in window-local pixels
        self._notnow_btn_rect = None
        self._last_text = ""           # for _resolve_click's button-only redraw
        self._last_color = "white"
        self._wave_bg = _render_wave_background()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.withdraw()  # start hidden until the first show()/show_recording()

        self._hwnd = _make_click_through(self.root)
        self.root.bind("<Button-1>", self._on_click_event)
        self.root.after(WAVE_TICK_MS, self._pump)
        _active_overlay = self

    # ---------- public, thread-safe API ----------

    def show(self, text, color="white", hide_after=None, on_click=None):
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        self._q.put(("show", text, color, hide_after, on_click, seq))

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
            _, text, color, hide_after, on_click, seq = cmd
            self._recording = False
            self._draw_status(text, color, on_click)
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
        self._on_click = None
        self._update_btn_rect = self._notnow_btn_rect = None
        _set_click_through(self._hwnd, True)
        self.root.withdraw()

    def _position(self, w, h):
        x, y = _rect_for(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        return x, y

    def _draw_status(self, text, color, on_click=None):
        self._position(PANEL_W, PANEL_H)
        self._last_text, self._last_color = text, color
        self._on_click = on_click
        interactive = on_click is not None
        if interactive:
            y0 = int(BTN_Y0)
            self._update_btn_rect = (UPDATE_X0, y0, UPDATE_X0 + UPDATE_W, y0 + BTN_H)
            self._notnow_btn_rect = (NOTNOW_X0, y0, NOTNOW_X0 + NOTNOW_W, y0 + BTN_H)
        else:
            self._update_btn_rect = self._notnow_btn_rect = None
        _push_layered_frame(self._hwnd, _render_status(text, color, interactive))
        _set_click_through(self._hwnd, not interactive)
        self.root.deiconify()

    def _on_click_event(self, event):
        # Bound directly on root rather than routed through a Canvas: once
        # this window is truly layered (UpdateLayeredWindow), Windows stops
        # delivering WM_PAINT to it or its children, so a Canvas widget's
        # own drawing would never be shown -- but mouse input still is,
        # which is all a plain root-level binding needs.
        if self._update_btn_rect and _point_in_rect(event.x, event.y, self._update_btn_rect):
            self._on_update_click()
        elif self._notnow_btn_rect and _point_in_rect(event.x, event.y, self._notnow_btn_rect):
            self._on_notnow_click()

    def _resolve_click(self, cb):
        # Clear the callback and re-arm click-through *before* invoking it,
        # so a second click delivered a moment later can never re-fire or
        # double-fire -- same ordering as overlay_mac's _resolve_. Redraws
        # without the buttons but keeps the same message text, matching Mac
        # (which hides the button views but doesn't touch the label) -- the
        # caller is expected to immediately show() a new message, except
        # "Not now" (cb is None), which has nothing coming and so withdraws
        # the pill outright, matching overlay_mac's handle_dismiss.
        text, color = self._last_text, self._last_color
        self._on_click = None
        self._update_btn_rect = self._notnow_btn_rect = None
        _set_click_through(self._hwnd, True)
        if cb is not None:
            _push_layered_frame(self._hwnd, _render_status(text, color, False))
            cb()
        else:
            self.root.withdraw()

    def _on_update_click(self):
        cb = self._on_click
        self._resolve_click(cb)

    def _on_notnow_click(self):
        self._resolve_click(None)

    def _draw_recording_frame(self):
        self._position(WAVE_PANEL_W, WAVE_PANEL_H)
        self._on_click = None
        self._update_btn_rect = self._notnow_btn_rect = None
        _set_click_through(self._hwnd, True)
        _push_layered_frame(self._hwnd, self._wave_bg)
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
        _push_layered_frame(self._hwnd, _render_wave_frame(self._wave_bg, amp, self._phase))


def _point_in_rect(x, y, rect):
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


def run_event_loop():
    """Blocks running the Tk mainloop on the main thread. Ctrl+C exits."""
    if _active_overlay is None:
        return
    try:
        _active_overlay.root.mainloop()
    except KeyboardInterrupt:
        pass
