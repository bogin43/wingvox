"""Floating status pill for Wingvox.

A small always-on-top panel at the bottom-center of the screen that shows
what the pipeline is doing (recording / transcribing / cleaning / errors).
It never steals focus from the app you're dictating into.

All public methods are thread-safe; UI work is dispatched to the main thread.
The process must run the AppKit event loop (see run_event_loop).
"""

import math
import threading

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSCompositingOperationCopy,
    NSDefaultRunLoopMode,
    NSEvent,
    NSEventMaskAny,
    NSFont,
    NSLeftMouseDown,
    NSMakeRect,
    NSPanel,
    NSRectFillUsingOperation,
    NSScreen,
    NSStatusWindowLevel,
    NSTextField,
    NSView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSDate, NSObject, NSProcessInfo, NSTimer
from PyObjCTools import AppHelper

PANEL_W, PANEL_H = 460, 40
COLORS = {
    "red": (1.0, 0.36, 0.36),
    "white": (0.95, 0.95, 0.95),
    "green": (0.35, 0.85, 0.45),
    "orange": (1.0, 0.65, 0.25),
    "gray": (0.7, 0.7, 0.7),
}
WAVE_TICK_HZ = 20.0
# The sqrt curve gives low levels a bigger boost than a linear scale would;
# raised so real speech visibly moves the waveform, not just a faint wobble.
WAVE_LEVEL_GAIN = 55.0
# Post-gain level (0..1) below which sound is treated as background noise
# (AC hum, room tone) and ignored entirely — only the level above the gate
# counts, rescaled back to a full 0..1 range. Raised alongside the gain above
# so ambient noise still gates fully to a flat line despite the higher gain.
NOISE_GATE = 0.4
# Smoothed level (0..1, after gating) at which the waveform reaches its
# maximum amplitude and clamps — full volume isn't required to peak it out.
MAX_AMPLITUDE_THRESHOLD = 0.55

WAVE_PANEL_W = 60
WAVE_PANEL_H = 26
WAVE_MARGIN = 3  # inset around the drawn waveform within the pill

# Layered sine strands drawn on top of each other (like a multi-line audio
# visualizer) — each is phase/amplitude-offset slightly for a denser, more
# organic look than a single clean sine wave.
WAVE_LINE_COUNT = 6
WAVE_LINE_ALPHA = 0.5
WAVE_LINE_WIDTH = 1.1
# Relative frequency/weight of each summed sine component (organic shape).
WAVE_COMPONENTS = [(1.6, 0.55), (3.1, 0.30), (5.0, 0.15)]


def _screen_under_cursor():
    """The screen containing the mouse cursor right now — this is what makes
    the pill follow you to whatever display you're actually working on,
    rather than always sitting on the display AppKit considers "main"
    (which, for our non-activating accessory app, doesn't reliably track
    where the user's focus/cursor actually is)."""
    loc = NSEvent.mouseLocation()
    for screen in NSScreen.screens():
        f = screen.frame()
        if f.origin.x <= loc.x <= f.origin.x + f.size.width and \
           f.origin.y <= loc.y <= f.origin.y + f.size.height:
            return screen
    return NSScreen.mainScreen()


def _rect_for(w, h):
    frame = _screen_under_cursor().frame()
    # Screens other than the primary one don't sit at origin (0, 0) in the
    # global coordinate space — omitting frame.origin here was the bug that
    # made the pill land in the wrong spot (or off-screen) on any display
    # besides the main MacBook.
    x = frame.origin.x + (frame.size.width - w) / 2
    y = frame.origin.y + 80
    return NSMakeRect(x, y, w, h)


class _WaveView(NSView):
    """Draws a small band of layered, animated sine strands, white-on-clear."""

    def initWithFrame_(self, frame):
        self = objc.super(_WaveView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.amplitude = 0.0  # 0..1, driven by live audio level
        self.phase = 0.0
        return self

    def isOpaque(self):
        return False

    def drawRect_(self, _rect):
        bounds = self.bounds()
        w, h = bounds.size.width, bounds.size.height
        # Layer-backed views normally redraw into a fresh transparent bitmap
        # each pass, but clear explicitly so old strokes never accumulate.
        NSColor.clearColor().set()
        NSRectFillUsingOperation(bounds, NSCompositingOperationCopy)

        cy = h / 2.0
        max_amp = h * 0.48
        amp = self.amplitude * max_amp
        steps = 90
        for i in range(WAVE_LINE_COUNT):
            line_amp = amp * (1.0 - i * 0.1)
            phase_off = i * 0.55
            path = NSBezierPath.bezierPath()
            path.setLineWidth_(WAVE_LINE_WIDTH)
            for s in range(steps + 1):
                t = s / steps
                x = w * t
                # Tapers the strand to a single point at each end (t=0, t=1)
                # instead of hard-clipping mid-wave at the view's edge.
                envelope = math.sin(math.pi * t)
                y = cy + line_amp * envelope * sum(
                    weight * math.sin(2 * math.pi * freq * t + self.phase + phase_off)
                    for freq, weight in WAVE_COMPONENTS
                )
                point = (x, y)
                if s == 0:
                    path.moveToPoint_(point)
                else:
                    path.lineToPoint_(point)
            NSColor.colorWithCalibratedWhite_alpha_(1.0, WAVE_LINE_ALPHA).setStroke()
            path.stroke()


BTN_H = 26
BTN_Y = (PANEL_H - BTN_H) / 2.0
NOTNOW_W = 74
UPDATE_W = 66
BTN_GAP = 8
BTN_RIGHT_MARGIN = 14
NOTNOW_X = PANEL_W - BTN_RIGHT_MARGIN - NOTNOW_W
UPDATE_X = NOTNOW_X - BTN_GAP - UPDATE_W
MSG_X = 16
MSG_W_INTERACTIVE = UPDATE_X - BTN_GAP - MSG_X


def _point_in_rect(point, rect):
    return (rect.origin.x <= point.x <= rect.origin.x + rect.size.width and
            rect.origin.y <= point.y <= rect.origin.y + rect.size.height)


class _Pill(NSObject):
    """Main-thread UI object. Do not call directly; use StatusOverlay."""

    def init(self):
        self = objc.super(_Pill, self).init()
        if self is None:
            return None
        rect = _rect_for(PANEL_W, PANEL_H)

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHidesOnDeactivate_(False)
        # show on every Space, including over full-screen apps
        panel.setCollectionBehavior_((1 << 0) | (1 << 8))

        content = panel.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setCornerRadius_(PANEL_H / 2)
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.88).CGColor()
        )

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, (PANEL_H - 20) / 2, PANEL_W - 32, 20)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(1)  # NSTextAlignmentCenter (unified iOS-style values)
        label.setFont_(NSFont.systemFontOfSize_weight_(14, 0.3))
        label.cell().setLineBreakMode_(4)  # truncate tail
        content.addSubview_(label)

        def _make_button(text, x, bg_rgba, text_rgb):
            view = NSView.alloc().initWithFrame_(NSMakeRect(x, BTN_Y, UPDATE_W, BTN_H))
            view.setWantsLayer_(True)
            btn_layer = view.layer()
            btn_layer.setCornerRadius_(BTN_H / 2)
            r, g, b, a = bg_rgba
            btn_layer.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a).CGColor())
            btn_label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, (BTN_H - 16) / 2, view.frame().size.width, 16))
            btn_label.setBezeled_(False)
            btn_label.setDrawsBackground_(False)
            btn_label.setEditable_(False)
            btn_label.setSelectable_(False)
            btn_label.setAlignment_(1)
            btn_label.setFont_(NSFont.systemFontOfSize_weight_(12, 0.4))
            btn_label.setStringValue_(text)
            tr, tg, tb = text_rgb
            btn_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(tr, tg, tb, 1.0))
            view.addSubview_(btn_label)
            view.setHidden_(True)
            content.addSubview_(view)
            return view

        update_btn = _make_button("Update", UPDATE_X, (0.30, 0.72, 0.42, 1.0), (1.0, 1.0, 1.0))
        update_btn.setFrame_(NSMakeRect(UPDATE_X, BTN_Y, UPDATE_W, BTN_H))
        notnow_btn = _make_button("Not now", NOTNOW_X, (1.0, 1.0, 1.0, 0.12), (0.82, 0.82, 0.82))
        notnow_btn.setFrame_(NSMakeRect(NOTNOW_X, BTN_Y, NOTNOW_W, BTN_H))
        # _make_button lays out its inner label using UPDATE_W for both calls above --
        # fix up notnow_btn's label width to match its own (wider) frame.
        notnow_btn.subviews()[0].setFrame_(NSMakeRect(0, (BTN_H - 16) / 2, NOTNOW_W, 16))

        wave_view = _WaveView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        wave_view.setHidden_(True)
        content.addSubview_(wave_view)

        self.panel = panel
        self.on_click = None  # armed only while showing an interactive state
        self.content_layer = layer
        self.label = label
        self.update_btn = update_btn
        self.notnow_btn = notnow_btn
        self.wave_view = wave_view
        self.timer = None
        self.peak = 0.0
        self.smoothed = 0.0
        panel.setIgnoresMouseEvents_(True)

        # A local event monitor, not a window/view mouseDown override: this app
        # runs an accessory-app console event loop (see run_event_loop) that
        # does not deliver sendEvent: to a non-key, non-activating panel the
        # way a normal windowed app's main loop would -- confirmed by testing
        # a sendEvent:-override approach, which never fired at all. A local
        # monitor taps NSApplication's own event stream directly instead, so
        # it isn't dependent on that per-window dispatch path.
        def _on_left_mouse_down(event):
            if event.window() == panel:
                pt = event.locationInWindow()
                if self.on_click is not None and _point_in_rect(pt, update_btn.frame()):
                    self.handle_click()
                    return None
                if self.on_click is not None and _point_in_rect(pt, notnow_btn.frame()):
                    self.handle_dismiss()
                    return None
            return event

        self._click_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            1 << NSLeftMouseDown, _on_left_mouse_down
        )
        return self

    def show_(self, payload):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        self.wave_view.setHidden_(True)
        self.panel.setFrame_display_(_rect_for(PANEL_W, PANEL_H), True)
        self.content_layer.setCornerRadius_(PANEL_H / 2)
        self.content_layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.88).CGColor()
        )
        self.label.setHidden_(False)
        text, color = payload["text"], payload.get("color", "white")
        r, g, b = COLORS.get(color, COLORS["white"])
        self.label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0))
        self.on_click = payload.get("on_click")
        interactive = self.on_click is not None
        if interactive:
            self.label.setFrame_(NSMakeRect(MSG_X, (PANEL_H - 20) / 2, MSG_W_INTERACTIVE, 20))
            self.label.setAlignment_(0)  # NSTextAlignmentLeft
        else:
            self.label.setFrame_(NSMakeRect(16, (PANEL_H - 20) / 2, PANEL_W - 32, 20))
            self.label.setAlignment_(1)  # NSTextAlignmentCenter
        self.label.setStringValue_(text)
        self.update_btn.setHidden_(not interactive)
        self.notnow_btn.setHidden_(not interactive)
        self.panel.setIgnoresMouseEvents_(not interactive)
        self.panel.orderFrontRegardless()

    def _resolve_(self, cb):
        # Clear the callback and re-arm click-through *before* invoking it,
        # so a second click delivered a moment later (or a stale reference
        # from a pill state that has since moved on) can never re-fire or
        # double-fire.
        self.on_click = None
        self.update_btn.setHidden_(True)
        self.notnow_btn.setHidden_(True)
        self.panel.setIgnoresMouseEvents_(True)
        if cb is not None:
            cb()

    def handle_click(self):
        cb = self.on_click
        self._resolve_(cb)

    def handle_dismiss(self):
        # "Not now" -- just dismiss, no callback into flow.py needed; this is
        # generic to any interactive pill, not specific to the update flow.
        self._resolve_(None)
        self.panel.orderOut_(None)

    def showRecording_(self, _):
        self.on_click = None
        self.update_btn.setHidden_(True)
        self.notnow_btn.setHidden_(True)
        self.panel.setIgnoresMouseEvents_(True)
        self.label.setHidden_(True)
        self.peak = 0.0
        self.smoothed = 0.0
        self.panel.setFrame_display_(_rect_for(WAVE_PANEL_W, WAVE_PANEL_H), True)
        self.content_layer.setCornerRadius_(WAVE_PANEL_H / 2)
        self.content_layer.setBackgroundColor_(NSColor.blackColor().CGColor())
        self.wave_view.setFrame_(
            NSMakeRect(
                WAVE_MARGIN, WAVE_MARGIN,
                WAVE_PANEL_W - WAVE_MARGIN * 2, WAVE_PANEL_H - WAVE_MARGIN * 2,
            )
        )
        self.wave_view.amplitude = 0.0
        self.wave_view.phase = 0.0
        self.wave_view.setHidden_(False)
        self.wave_view.setNeedsDisplay_(True)
        self.panel.orderFrontRegardless()
        if self.timer is None:
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / WAVE_TICK_HZ, self, "tick:", None, True
            )

    def tick_(self, _timer):
        lvl = min(1.0, (self.peak * WAVE_LEVEL_GAIN) ** 0.5)
        self.peak = 0.0
        lvl = max(0.0, (lvl - NOISE_GATE) / (1.0 - NOISE_GATE))  # gate out background noise
        if lvl > self.smoothed:
            self.smoothed = self.smoothed * 0.3 + lvl * 0.7  # fast attack ("flash" in)
        else:
            self.smoothed = self.smoothed * 0.75 + lvl * 0.25  # slower release
        amp = min(1.0, self.smoothed / MAX_AMPLITUDE_THRESHOLD)
        self.wave_view.amplitude = amp
        # Keeps waving gently even near silence rather than freezing solid;
        # picks up pace as the amplitude (and so the volume) rises.
        self.wave_view.phase += 0.05 + amp * 0.22
        self.wave_view.setNeedsDisplay_(True)

    def pushRawLevel_(self, rms):
        if rms > self.peak:
            self.peak = rms

    def hide_(self, _):
        self.on_click = None
        self.update_btn.setHidden_(True)
        self.notnow_btn.setHidden_(True)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.orderOut_(None)


class StatusOverlay:
    """Thread-safe handle to the pill. Create once, then call show()/hide()."""

    def __init__(self):
        self._pill = _Pill.alloc().init()
        self._seq = 0
        self._lock = threading.Lock()

    def show(self, text, color="white", hide_after=None, on_click=None):
        with self._lock:
            self._seq += 1
            seq = self._seq
        self._pill.performSelectorOnMainThread_withObject_waitUntilDone_(
            "show:", {"text": text, "color": color, "on_click": on_click}, False
        )
        if hide_after is not None:
            threading.Timer(hide_after, self._hide_if_current, args=(seq,)).start()

    def show_recording(self):
        with self._lock:
            self._seq += 1
        self._pill.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showRecording:", None, False
        )

    def push_level(self, rms):
        self._pill.pushRawLevel_(rms)

    def hide(self):
        with self._lock:
            self._seq += 1
        self._pill.performSelectorOnMainThread_withObject_waitUntilDone_("hide:", None, False)

    def _hide_if_current(self, seq):
        with self._lock:
            if seq != self._seq:  # a newer message replaced this one
                return
        self._pill.performSelectorOnMainThread_withObject_waitUntilDone_("hide:", None, False)


def run_event_loop():
    """Start the AppKit event loop on the main thread (blocks). Ctrl+C exits.

    Deliberately NOT AppHelper.runConsoleEventLoop: that helper only pumps
    NSRunLoop directly (fine for timers, which is all this pill needed before
    it became clickable) -- it never calls NSApp.nextEventMatchingMask_/
    sendEvent_, so window mouse events are never retrieved from the window
    server at all, let alone dispatched. Confirmed by testing: neither a
    window sendEvent: override nor an NSEvent local monitor ever fired a
    single time under runConsoleEventLoop, because the event was never being
    pulled off the queue in the first place. This loop pumps and dispatches
    events manually instead, the same way NSApp.run() would, while keeping
    the bounded per-iteration wait (rather than an indefinite one) so a
    pending Ctrl+C still gets a chance to be delivered between iterations."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    # With no visible window most of the time, macOS's Automatic Termination
    # (App Nap infrastructure) is otherwise free to silently kill this process
    # when idle -- a clean exit(0), no crash, no traceback, just gone. This
    # process must keep running indefinitely to catch the hotkey, so opt out.
    NSProcessInfo.processInfo().disableAutomaticTermination_("Wingvox must run continuously to catch the hotkey")
    AppHelper.installMachInterrupt()
    while True:
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny,
            NSDate.dateWithTimeIntervalSinceNow_(1.0),
            NSDefaultRunLoopMode,
            True,
        )
        if event is not None:
            app.sendEvent_(event)
            app.updateWindows()
