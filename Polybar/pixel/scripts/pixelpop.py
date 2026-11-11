#!/usr/bin/env python3
"""pixelpop: pixel-art popups that drop out of polybar.

    pixelpop.py calendar | network | volume | power | sysinfo | session
    pixelpop.py switcher   (Alt+Tab: hold Alt, tap Tab to cycle, release to switch)
    pixelpop.py overview   (same cards, click / Enter to switch)

Clicking the same module again (or anywhere outside the popup, or Esc) closes it.
Popups slide out from under the bar with a Bayer-dither dissolve.
"""
import calendar
import datetime
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import threading


def _click_point():
    """Pointer position right after the click, read before the slow GTK import
    (~175ms) so moving the mouse away afterwards can't change it."""
    try:
        out = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                             capture_output=True, text=True, timeout=1).stdout
        g = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        return int(g["X"]), int(g["Y"])
    except (OSError, subprocess.TimeoutExpired, KeyError, ValueError):
        return None


CLICK = _click_point()

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

# ---------------------------------------------------------------- theme ----
THEME_COLORS = os.path.expanduser("~/Desktop/dotfiles/themes/current/colors")


def theme_colors(defaults):
    """The current theme's colours (written by dotfiles/Scripts/theme.py), else defaults."""
    c = dict(defaults)
    try:
        with open(THEME_COLORS) as f:
            for line in f:
                k, eq, v = line.strip().partition("=")
                if eq and k in c and len(v) == 7 and v.startswith("#"):
                    c[k] = v
    except OSError:
        pass
    return c


C = theme_colors(dict(
    bg="#353E40",
    bg_alt="#3d474a",
    bg_hi="#43504f",
    border="#4a5659",
    fg="#d8d2c8",
    dim="#8a949a",
    accent="#8DB38B",
    warn="#d8a657",
    alert="#c96a5f",
))
FONT = "Terminus"      # same bitmap font as the bar (icons fall back to Symbols Nerd Font)
FONT_PX = 18           # Terminus bitmap sizes: 12 14 16 18 20 22 24 28 32
BIG_PX = 28
PIXEL = 4              # dissolve cell size (px)
ANIM_MS = 160          # open animation length
BAR_FALLBACK_H = 34    # used if the polybar window can't be found

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUN, "pixelpop.pid")
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]

CSS = f"""
* {{
    font-family: "{FONT}";
    font-size: {FONT_PX}px;
    color: {C['fg']};
    text-shadow: none;
    -gtk-icon-shadow: none;
    box-shadow: none;
    outline: none;
    border-radius: 0;
    background-image: none;
}}
window, #frame {{ background-color: {C['bg']}; }}
#frame {{
    border: 2px solid {C['border']};
    border-top-width: 0;
    padding: 8px 12px 12px 12px;
}}
.title {{ color: {C['accent']}; }}
.big {{ font-size: {BIG_PX}px; }}
.dim {{ color: {C['dim']}; }}
.accent {{ color: {C['accent']}; }}
.warn {{ color: {C['warn']}; }}
.alert {{ color: {C['alert']}; }}
.sep {{ background-color: {C['border']}; min-height: 2px; }}
button {{
    background-color: {C['bg_alt']};
    border: 2px solid {C['border']};
    padding: 1px 8px;
    min-height: 0;
    min-width: 0;
}}
button:hover {{ border-color: {C['accent']}; }}
button:hover label {{ color: {C['accent']}; }}
button.flat {{ background-color: transparent; border-color: transparent; padding: 2px 6px; }}
button.flat:hover {{ border-color: {C['border']}; }}
button.sel, button.sel:hover {{ background-color: {C['accent']}; border-color: {C['accent']}; }}
button.sel label, button.sel:hover label {{ color: {C['bg']}; }}
button.danger:hover {{ border-color: {C['alert']}; }}
button.card {{ background-color: {C['bg_alt']}; padding: 6px; }}
button.card.picked {{ border-color: {C['accent']}; background-color: {C['bg_hi']}; }}
button.card.picked .cardname {{ color: {C['accent']}; }}
.thumb {{ border: 2px solid {C['border']}; }}
button.card.picked .thumb {{ border-color: {C['accent']}; }}
button.danger:hover label {{ color: {C['alert']}; }}
button.armed, button.armed:hover {{ background-color: {C['alert']}; border-color: {C['alert']}; }}
button.armed label {{ color: {C['bg']}; }}
.day {{ padding: 2px 8px; }}
.today {{ background-color: {C['accent']}; }}
.today label {{ color: {C['bg']}; }}
entry {{
    background-color: {C['bg_alt']};
    border: 2px solid {C['border']};
    padding: 2px 8px;
    caret-color: {C['accent']};
}}
entry:focus {{ border-color: {C['accent']}; }}
scrollbar, scrollbar slider {{ background-color: {C['bg']}; border: 0; min-width: 4px; }}
scrollbar slider {{ background-color: {C['border']}; }}
"""


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def run(cmd, inp=None, timeout=30):
    try:
        p = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def label(text="", cls=(), xalign=0.0):
    lb = Gtk.Label(label=text)
    lb.set_xalign(xalign)
    for c in cls:
        lb.get_style_context().add_class(c)
    return lb


def button(text, cb, cls=()):
    b = Gtk.Button(label=text)
    for c in cls:
        b.get_style_context().add_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def set_cls(widget, cls, on):
    ctx = widget.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(cls)


def sep():
    s = Gtk.Box()
    s.get_style_context().add_class("sep")
    s.set_margin_top(6)
    s.set_margin_bottom(6)
    return s


def in_thread(work, done):
    """Run work() off the UI thread, then done(result) on it."""
    def go():
        r = work()
        GLib.idle_add(lambda: (done(r), False)[1])
    threading.Thread(target=go, daemon=True).start()


# ------------------------------------------------------------ widgets ----
class PixelBar(Gtk.DrawingArea):
    """Segmented usage bar: ■■■■□□□□"""

    def __init__(self, segments=14, seg_w=6, gap=2, height=12, high_good=False, neutral=False):
        super().__init__()
        self.n, self.sw, self.gap, self.h = segments, seg_w, gap, height
        self.high_good = high_good  # battery/health: low is bad, high is fine
        self.neutral = neutral      # e.g. clock speed: neither high nor low is bad
        self.value = 0.0
        self.set_size_request(segments * (seg_w + gap) - gap, height)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self.on_draw)

    def set_value(self, pct):
        self.value = max(0.0, min(100.0, pct))
        self.queue_draw()

    def on_draw(self, _w, cr):
        filled = round(self.value / 100 * self.n)
        if self.value > 0 and filled == 0:
            filled = 1
        if self.neutral:
            col = C["accent"]
        elif self.high_good:
            col = C["accent"] if self.value >= 30 else C["warn"] if self.value >= 15 else C["alert"]
        else:
            col = C["accent"] if self.value < 75 else C["warn"] if self.value < 90 else C["alert"]
        for i in range(self.n):
            cr.set_source_rgb(*rgb(col if i < filled else C["border"]))
            cr.rectangle(i * (self.sw + self.gap), 0, self.sw, self.h)
            cr.fill()


class SignalBars(Gtk.DrawingArea):
    """Four stepped pixel bars for Wi-Fi signal."""

    def __init__(self, signal_pct, active=False):
        super().__init__()
        self.level = 0 if signal_pct < 20 else 1 if signal_pct < 45 else 2 if signal_pct < 70 else 3
        self.level += 1
        self.active = active
        self.set_size_request(18, 14)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self.on_draw)

    def on_draw(self, _w, cr):
        on = C["accent"] if self.active else C["fg"]
        for i in range(4):
            h = 5 + i * 3
            cr.set_source_rgb(*rgb(on if i < self.level else C["border"]))
            cr.rectangle(i * 5, 14 - h, 3, h)
            cr.fill()


class BatteryGraph(Gtk.DrawingArea):
    """Battery % over time as columns of pixel cells; a strip under a column = charging.
    Reads the log written by battery_log.sh (started by i3); columns with no data
    (laptop off or asleep) stay empty."""
    COLS, CELL, GAP, ROWS = 48, 4, 1, 12

    def __init__(self):
        super().__init__()
        self.hours = BATTERY_SPANS[1]
        self.points = []
        step = self.CELL + self.GAP
        self.w = self.COLS * step - self.GAP
        self.gh = self.ROWS * step - self.GAP  # graph height, charging strip goes below
        self.set_size_request(self.w, self.gh + 4)
        self.set_halign(Gtk.Align.START)
        self.connect("draw", self.on_draw)

    def update(self, live):
        """live = (cap, status) right now, so the newest column is never stale."""
        now = int(datetime.datetime.now().timestamp())
        self.points = battery_history(now - self.hours * 3600)
        if live:
            self.points.append((now, live[0], live[1]))
        self.queue_draw()

    def columns(self):
        now = datetime.datetime.now().timestamp()
        start = now - self.hours * 3600
        dt = self.hours * 3600 / self.COLS
        cols = [None] * self.COLS
        for t, cap, st in self.points:  # sorted by time, so the last sample in a column wins
            i = int((t - start) / dt)
            if 0 <= i < self.COLS:
                cols[i] = (cap, st)
        return cols

    def on_draw(self, _w, cr):
        step = self.CELL + self.GAP
        for i, v in enumerate(self.columns()):
            x = i * step
            filled = 0
            if v is not None:
                filled = max(1, round(v[0] / 100 * self.ROWS))
                col = C["accent"] if v[0] >= 30 else C["warn"] if v[0] >= 15 else C["alert"]
            for r in range(self.ROWS):  # bottom row first
                y = self.gh - (r + 1) * step + self.GAP
                cr.set_source_rgb(*rgb(col if r < filled else C["bg_alt"]))
                cr.rectangle(x, y, self.CELL, self.CELL)
                cr.fill()
            if v is not None and v[1] in ("Charging", "Full"):
                cr.set_source_rgb(*rgb(C["fg"]))
                cr.rectangle(x, self.gh + 2, self.CELL, 2)
                cr.fill()


def stat_row(grid, row, name, bar, value_lbl, extra=None):
    grid.attach(label(name, ("dim",)), 0, row, 1, 1)
    grid.attach(bar, 1, row, 1, 1)
    grid.attach(value_lbl, 2, row, 1, 1)
    if extra is not None:
        grid.attach(extra, 3, row, 1, 1)


# -------------------------------------------------------------- popup ----
class Popup(Gtk.Window):
    def __init__(self, kind):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.kind = kind
        self.reveal = 0.0
        self.anim_start = None

        overlay = Gtk.Overlay()
        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.set_name("frame")
        overlay.add(self.frame)
        self.cover = Gtk.DrawingArea()
        self.cover.connect("draw", self.draw_cover)
        overlay.add_overlay(self.cover)
        overlay.set_overlay_pass_through(self.cover, True)
        self.add(overlay)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("scroll-event", self.on_scroll_any)
        self.dragging = None
        self.connect("key-press-event", self.on_key)

    # -- placement --------------------------------------------------------
    def place_and_show(self):
        self.frame.show_all()
        self.get_child().show()
        self.cover.show()
        _min, nat = self.get_preferred_size()
        w, h = nat.width, nat.height

        display = Gdk.Display.get_default()
        if CLICK:
            px, py = CLICK
        else:
            _scr, px, py = display.get_default_seat().get_pointer().get_position()
        mon = display.get_monitor_at_point(px, py).get_geometry()

        bar = bar_geometry(mon)
        # hang centred under the module that opened us, not under the mouse
        span = module_span(bar, self.kind, px) if bar else None
        cx = (span[0] + span[1]) // 2 if span else px
        x = max(mon.x, min(cx - w // 2, mon.x + mon.width - w))
        if bar:  # keep the popup within the bar's width (the bar has gaps)
            left, right, y = bar[:3]
            x = max(left, min(x, right - w))
        else:
            y = mon.y + BAR_FALLBACK_H
        self.move(x, y)
        self.show()
        self.anim_start = GLib.get_monotonic_time()
        GLib.timeout_add(16, self.tick)
        self.grab_tries = 0
        GLib.timeout_add(30, self.try_grab)

    def try_grab(self):
        gdkwin = self.get_window()
        if gdkwin is None:
            return True
        seat = Gdk.Display.get_default().get_default_seat()
        st = seat.grab(gdkwin, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        if st == Gdk.GrabStatus.SUCCESS:
            gdkwin.focus(Gdk.CURRENT_TIME)
            self.on_grabbed()
            return False
        self.grab_tries += 1
        # polybar (click) or i3 (key binding) may still hold the grab; retry ~3s
        return self.grab_tries < 100

    def on_grabbed(self):
        pass

    # -- open animation: slide + Bayer dither -----------------------------
    def tick(self):
        t = (GLib.get_monotonic_time() - self.anim_start) / 1000 / ANIM_MS
        self.reveal = min(1.0, t)
        self.cover.queue_draw()
        if self.reveal >= 1.0:
            self.cover.hide()
            return False
        return True

    def draw_cover(self, w, cr):
        if self.reveal >= 1.0:
            return
        W, H = w.get_allocated_width(), w.get_allocated_height()
        band = 96.0
        front = self.reveal * (H + band)  # dissolve front moves down from the bar
        cr.set_source_rgb(*rgb(C["bg"]))
        for cy in range(0, H, PIXEL):
            v = (front - cy) / band
            if v >= 1.0:
                continue
            if v <= 0.0:
                cr.rectangle(0, cy, W, H - cy)
                break
            row = BAYER[(cy // PIXEL) % 4]
            for cx in range(0, W, PIXEL):
                if row[(cx // PIXEL) % 4] / 16 >= v:
                    cr.rectangle(cx, cy, PIXEL, PIXEL)
        cr.fill()

    # -- closing ----------------------------------------------------------
    def on_press(self, _w, ev):
        gdkwin = self.get_window()
        ox, oy = gdkwin.get_origin()[1:]
        w, h = self.get_size()
        if not (ox <= ev.x_root < ox + w and oy <= ev.y_root < oy + h):
            self.quit()
            return True
        if ev.button == 1 and ev.type == Gdk.EventType.BUTTON_PRESS:
            for sl in PixelSlider.all:
                x = sl.hit(ev.x_root, ev.y_root)
                if x is not None:
                    self.dragging = sl
                    sl.drag = True
                    sl.from_x(x)
                    return True
        return False

    def on_motion(self, _w, ev):
        if self.dragging is not None:
            self.dragging.drag_to(ev.x_root, ev.y_root)
            return True
        return False

    def on_release(self, _w, ev):
        if self.dragging is not None:
            self.dragging.drag = False
            self.dragging = None
            return True
        return False

    def on_scroll_any(self, w, ev):
        for sl in PixelSlider.all:
            if sl.hit(ev.x_root, ev.y_root) is not None:
                return sl.on_scroll(w, ev)
        return False

    def on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.quit()
            return True
        return False

    def quit(self, *_):
        try:
            if read(PIDFILE).split()[0] == str(os.getpid()):
                os.unlink(PIDFILE)
        except (OSError, IndexError):
            pass
        Gtk.main_quit()


CONFIG = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "config.ini")
# popup kind -> the bar module(s) that open it (names from modules-right)
KIND_MODULES = dict(calendar=["date"], sysinfo=["cpu", "memory"], network=["network"],
                    volume=["pulseaudio"], power=["battery"], session=["session"])
GAP_PX = 48  # this much empty bar ends a module that has no separator on that side


def modules_right():
    try:
        with open(CONFIG) as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == "modules-right":
                    return v.split()
    except OSError:
        pass
    return []


def module_span(bar, kind, px):
    """(left, right) screen x of the drawn content of the module for `kind`.

    Reads the bar's pixels: modules-right are split by the `separator` glyph
    (a full-height column of colors.border), so module i of modules-right sits
    between separators i-1 and i. That pins each popup to its module however
    the mouse moves. Returns None if the bar doesn't look as expected."""
    try:
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11
        wx, wid = bar[0], bar[3]
        win = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), wid)
        W, H = win.get_width(), win.get_height()
        pb = Gdk.pixbuf_get_from_window(win, 0, 0, W, H)
    except Exception:  # noqa: BLE001 - any failure: fall back to the click point
        return None
    if pb is None:
        return None
    px_, rs, nc = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
    bg, sepc = bytes(rgb_bytes(C["bg"])), bytes(rgb_bytes(C["border"]))
    rows = range(3, H - 3)  # skip the 2px bar border

    def pixel(x, y):
        o = y * rs + x * nc
        return px_[o:o + 3]

    def is_sep(x):
        run = best = 0
        for y in rows:
            run = run + 1 if pixel(x, y) == sepc else 0
            best = max(best, run)
        return 12 <= best < len(rows)  # tall like the │ glyph, not the bar's side border

    def blank(x):
        return all(pixel(x, y) == bg for y in rows)

    L, R = 2, W - 2  # inside the bar's 2px side borders
    seps = []
    for x in range(L, R):
        if is_sep(x) and not (seps and x - seps[-1] <= 2):
            seps.append(x)

    mods = modules_right()
    names = KIND_MODULES.get(kind, [])
    lx = px - wx
    if len(seps) == len(mods) - 1 and any(n in mods for n in names):
        cand = [mods.index(n) for n in names if n in mods]
        # sysinfo has two modules (cpu, ram): use the one that was clicked
        bounds = lambda i: (seps[i - 1] if i else None, seps[i] if i < len(seps) else R)  # noqa: E731
        i = next((i for i in cand if (bounds(i)[0] or 0) <= lx <= bounds(i)[1]), cand[0])
        lo, hi = bounds(i)
    else:  # unknown layout: take the module under the click
        lo = max((s for s in seps if s < lx), default=None)
        hi = min((s for s in seps if s > lx), default=R)

    # trim to drawn content; a module without a left separator ends at a wide gap
    xs = []
    gap = 0
    start = hi - 1
    stop = (lo + 1) if lo is not None else L
    for x in range(start, stop - 1, -1):
        if is_sep(x):
            continue
        if blank(x):
            gap += 1
            if lo is None and xs and gap >= GAP_PX:
                break
        else:
            gap = 0
            xs.append(x)
    if not xs:
        return None
    return wx + min(xs), wx + max(xs) + 1


def rgb_bytes(hexstr):
    h = hexstr.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def bar_geometry(mon):
    """(left, right, bottom, xid) of the top polybar window on this monitor, or None."""
    rc, out, _ = run(["xdotool", "search", "--classname", "polybar"], timeout=2)
    best = None
    for wid in out.split():
        rc, geo, _ = run(["xdotool", "getwindowgeometry", "--shell", wid], timeout=2)
        g = dict(line.split("=", 1) for line in geo.splitlines() if "=" in line)
        try:
            x, y, w, h = (int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
        except (KeyError, ValueError):
            continue
        if h < 8 or not (mon.x <= x < mon.x + mon.width):
            continue
        if y <= mon.y + mon.height // 2 and (best is None or y + h > best[2]):
            best = (x, x + w, y + h, int(wid))
    return best


# ============================================================ calendar ====
class CalendarPopup(Popup):
    def __init__(self):
        super().__init__("calendar")
        today = datetime.date.today()
        self.year, self.month = today.year, today.month

        self.clock = label("", ("big",), 0.5)
        self.datel = label("", ("dim",), 0.5)
        self.frame.pack_start(self.clock, False, False, 0)
        self.frame.pack_start(self.datel, False, False, 0)
        self.frame.pack_start(sep(), False, False, 0)

        nav = Gtk.Box(spacing=6)
        nav.pack_start(button("", lambda: self.shift(-1), ("flat",)), False, False, 0)
        self.title = button("", self.go_today, ("flat",))
        nav.pack_start(self.title, True, True, 0)
        nav.pack_end(button("", lambda: self.shift(1), ("flat",)), False, False, 0)
        self.frame.pack_start(nav, False, False, 4)

        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=2, column_spacing=2)
        ev = Gtk.EventBox()
        ev.add(self.grid)
        ev.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        ev.connect("scroll-event", self.on_scroll)
        self.frame.pack_start(ev, False, False, 0)

        self.frame.pack_start(sep(), False, False, 0)
        self.foot = label("", ("dim",), 0.5)
        self.frame.pack_start(self.foot, False, False, 0)

        self.render()
        self.tick_clock()
        GLib.timeout_add(1000, self.tick_clock)

    def tick_clock(self):
        now = datetime.datetime.now()
        self.clock.set_text(now.strftime("%H:%M:%S"))
        self.datel.set_text(now.strftime("%A %d %B %Y"))
        return True

    def shift(self, d):
        m = self.month - 1 + d
        self.year += m // 12
        self.month = m % 12 + 1
        self.render()

    def go_today(self):
        t = datetime.date.today()
        self.year, self.month = t.year, t.month
        self.render()

    def on_scroll(self, _w, ev):
        if ev.direction == Gdk.ScrollDirection.UP:
            self.shift(-1)
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            self.shift(1)
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            self.shift(-1 if ev.delta_y < 0 else 1)
        return True

    def render(self):
        for ch in self.grid.get_children():
            self.grid.remove(ch)
        self.title.set_label(datetime.date(self.year, self.month, 1).strftime("%B %Y"))
        for i, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            self.grid.attach(label(d, ("accent" if i < 5 else "dim",), 0.5), i, 0, 1, 1)
        today = datetime.date.today()
        weeks = calendar.Calendar(0).monthdatescalendar(self.year, self.month)
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                cls = ["day"]
                if day.month != self.month:
                    cls.append("dim")
                box = Gtk.EventBox()
                lb = label(f"{day.day:2d}", cls, 0.5)
                box.add(lb)
                if day == today:
                    box.get_style_context().add_class("today")
                self.grid.attach(box, c, r, 1, 1)
        wk = datetime.date(self.year, self.month, 1).isocalendar()[1]
        self.foot.set_text(f"week {wk}  ·  scroll to change month")
        self.grid.show_all()


# ============================================================= network ====
def nm_unescape(s):
    return s.replace("\\:", ":").replace("\\\\", "\\")


def nm_split(line):
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


class NetworkPopup(Popup):
    def __init__(self):
        super().__init__("network")
        head = Gtk.Box(spacing=10)
        head.pack_start(label("Network", ("title",)), True, True, 0)
        self.rescan_b = button("\U000f0450", self.rescan, ("flat",))
        head.pack_end(self.rescan_b, False, False, 0)
        self.toggle_b = button("", self.toggle_wifi)
        head.pack_end(self.toggle_b, False, False, 0)
        self.frame.pack_start(head, False, False, 0)

        self.status = Gtk.Grid(column_spacing=10, row_spacing=2)
        self.frame.pack_start(self.status, False, False, 6)
        self.frame.pack_start(sep(), False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_min_content_height(250)
        sc.set_max_content_height(250)
        sc.set_min_content_width(360)
        sc.add(self.list)
        self.frame.pack_start(sc, True, True, 0)

        self.msg = label("", ("dim",))
        self.msg.set_line_wrap(True)
        self.msg.set_max_width_chars(34)
        self.frame.pack_start(self.msg, False, False, 6)

        self.pass_box = None
        self.refresh()

    # -- data -------------------------------------------------------------
    def load(self):
        d = {}
        _, radio, _ = run(["nmcli", "radio", "wifi"])
        d["radio"] = radio == "enabled"
        _, devs, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        d["devices"] = [nm_split(l) for l in devs.splitlines()]
        _, route, _ = run(["ip", "-o", "route", "show", "default"])
        parts = route.split()
        d["default"] = parts[parts.index("dev") + 1] if "dev" in parts else ""
        d["ip"] = ""
        if d["default"]:
            _, a, _ = run(["ip", "-o", "-4", "addr", "show", "dev", d["default"]])
            for tok in a.split():
                if "/" in tok and tok[0].isdigit():
                    d["ip"] = tok.split("/")[0]
                    break
        d["bitrate"] = ""
        if d["default"] and os.path.isdir(f"/sys/class/net/{d['default']}/wireless"):
            _, link, _ = run(["iw", "dev", d["default"], "link"])
            for l in link.splitlines():
                if "rx bitrate:" in l:
                    d["bitrate"] = " ".join(l.split()[2:4])
        elif d["default"]:
            sp = read(f"/sys/class/net/{d['default']}/speed")
            if sp.isdigit() and int(sp) > 0:
                d["bitrate"] = f"{sp} Mbit/s"
        _, saved, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        d["saved"] = {nm_split(l)[0] for l in saved.splitlines() if l.endswith(":802-11-wireless")}
        nets, seen = [], set()
        if d["radio"]:
            _, wl, _ = run(["nmcli", "-t", "-f", "IN-USE,SIGNAL,SECURITY,SSID", "device", "wifi", "list", "--rescan", "no"])
            rows = [nm_split(l) for l in wl.splitlines()]
            rows = [r for r in rows if len(r) >= 4]
            rows.sort(key=lambda r: (r[0] != "*", -int(r[1] or 0)))
            for inuse, sig, sec, ssid in (r[:4] for r in rows):
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                nets.append(dict(active=inuse == "*", signal=int(sig or 0),
                                 secure=sec not in ("", "--"), sec=sec, ssid=ssid))
        d["nets"] = nets
        return d

    def refresh(self):
        in_thread(self.load, self.show_data)

    def show_data(self, d):
        self.data = d
        self.toggle_b.set_label("Wi-Fi on" if d["radio"] else "Wi-Fi off")
        set_cls(self.toggle_b, "sel", d["radio"])

        for ch in self.status.get_children():
            self.status.remove(ch)
        conn = [x for x in d["devices"] if len(x) >= 4 and x[2] == "connected" and x[1] in ("wifi", "ethernet")]
        if not conn:
            self.status.attach(label("\U000f092e  not connected", ("alert",)), 0, 0, 2, 1)
        r = 0
        for dev, typ, _st, name in conn:
            icon = "\U000f05a9" if typ == "wifi" else "\U000f0200"
            star = "  • default" if dev == d["default"] else ""
            self.status.attach(label(f"{icon}  {name}", ("accent",)), 0, r, 2, 1)
            r += 1
            self.status.attach(label(f"{dev}{star}", ("dim",)), 0, r, 2, 1)
            r += 1
        if d["ip"]:
            self.status.attach(label("ip", ("dim",)), 0, r, 1, 1)
            self.status.attach(label(d["ip"]), 1, r, 1, 1)
            r += 1
        if d["bitrate"]:
            self.status.attach(label("link", ("dim",)), 0, r, 1, 1)
            self.status.attach(label(d["bitrate"]), 1, r, 1, 1)
        self.status.show_all()

        for ch in self.list.get_children():
            self.list.remove(ch)
        self.pass_box = None
        self.rows = {}
        if not d["radio"]:
            self.list.pack_start(label("Wi-Fi is off", ("dim",)), False, False, 0)
        elif not d["nets"]:
            self.list.pack_start(label("no networks found", ("dim",)), False, False, 0)
        for n in d["nets"]:
            self.list.pack_start(self.net_row(n), False, False, 0)
        self.list.show_all()

    def net_row(self, n):
        b = Gtk.Button()
        b.get_style_context().add_class("flat")
        row = Gtk.Box(spacing=12)
        row.pack_start(SignalBars(n["signal"], n["active"]), False, False, 0)
        name = n["ssid"] if len(n["ssid"]) <= 22 else n["ssid"][:21] + "…"
        row.pack_start(label(name, ("accent",) if n["active"] else ()), True, True, 0)
        tail = ""
        if n["ssid"] in self.data["saved"]:
            tail += "\U000f0193 "  # saved
        if n["secure"]:
            tail += "\U000f033e"
        row.pack_end(label(tail, ("dim",), 1.0), False, False, 0)
        b.add(row)
        b.connect("clicked", lambda *_: self.pick(n, b))
        self.rows[n["ssid"]] = b
        return b

    # -- actions ----------------------------------------------------------
    def say(self, text, cls="dim"):
        for c in ("dim", "accent", "alert", "warn"):
            set_cls(self.msg, c, c == cls)
        self.msg.set_text(text)

    def pick(self, n, row_btn):
        if n["active"]:
            self.say(f"Disconnecting {n['ssid']}…")
            dev = next((x[0] for x in self.data["devices"] if x[1] == "wifi"), "")
            in_thread(lambda: run(["nmcli", "device", "disconnect", dev]), lambda r: self.after(r, "Disconnected"))
            return
        if n["ssid"] in self.data["saved"] or not n["secure"]:
            self.connect_to(n, None)
            return
        if "802.1X" in n["sec"]:
            self.say("Enterprise (802.1X) networks need nm-connection-editor", "warn")
            return
        self.ask_password(n, row_btn)

    def ask_password(self, n, row_btn):
        if self.pass_box:
            self.list.remove(self.pass_box)
        box = Gtk.Box(spacing=6)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text("password")
        entry.set_hexpand(True)
        go = lambda *_: self.connect_to(n, entry.get_text())  # noqa: E731
        entry.connect("activate", go)
        box.pack_start(entry, True, True, 0)
        box.pack_start(button("\U000f0142", go), False, False, 0)
        kids = self.list.get_children()
        self.list.pack_start(box, False, False, 0)
        self.list.reorder_child(box, kids.index(row_btn) + 1)
        box.show_all()
        self.pass_box = box
        entry.grab_focus()

    def connect_to(self, n, password):
        ssid = n["ssid"]
        self.say(f"Connecting to {ssid}…", "warn")
        saved = ssid in self.data["saved"]

        def work():
            if saved and password is None:
                return run(["nmcli", "--wait", "25", "connection", "up", "id", ssid], timeout=40)
            cmd = ["nmcli", "--wait", "25", "device", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            r = run(cmd, timeout=40)
            if r[0] != 0 and not saved:
                run(["nmcli", "connection", "delete", "id", ssid])
            return r

        def done(r):
            if r[0] != 0 and saved and n["secure"] and password is None:
                self.say("Saved password failed, enter it again", "alert")
                row = self.rows.get(ssid)
                if row:
                    self.ask_password(n, row)
                return
            self.after(r, f"Connected to {ssid}")

        in_thread(work, done)

    def after(self, r, ok_text):
        if r[0] == 0:
            self.say(ok_text, "accent")
        else:
            err = (r[2] or r[1]).splitlines()[-1:] or ["failed"]
            self.say(err[0].replace("Error: ", ""), "alert")
        self.refresh()

    def toggle_wifi(self):
        on = self.data.get("radio") if hasattr(self, "data") else True
        self.say("Turning Wi-Fi off…" if on else "Turning Wi-Fi on…")
        in_thread(lambda: run(["nmcli", "radio", "wifi", "off" if on else "on"]),
                  lambda r: (self.say(""), GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])))

    def rescan(self):
        self.say("Scanning…")
        in_thread(lambda: (run(["nmcli", "device", "wifi", "rescan"]), GLib.usleep(2500000)),
                  lambda _r: (self.say(""), self.refresh()))


# ============================================================== volume ====
class PixelSlider(Gtk.Box):
    """Clickable / draggable / scrollable segmented slider.

    Input is routed here by Popup (see Popup.slider_event): under the popup's
    pointer grab GTK doesn't reliably deliver clicks to child widgets, and a
    drag has to keep working when the pointer leaves the slider.
    """

    def __init__(self, on_change, segments=20, gap=2, height=16, min_width=260):
        super().__init__()
        self.n, self.gap, self.h = segments, gap, height
        self.value, self.muted, self.drag = 0, False, False
        self.on_change = on_change
        da = Gtk.DrawingArea()
        da.set_size_request(min_width, height)
        da.set_hexpand(True)
        da.connect("draw", self.on_draw)
        self.da = da
        self.pack_start(da, True, True, 0)
        PixelSlider.all.append(self)

    def set(self, v, notify=False):
        v = max(0, min(100, int(round(v))))
        changed = v != self.value
        self.value = v
        self.da.queue_draw()
        if notify and changed:
            self.on_change(v)

    all = []

    def local(self, x_root, y_root):
        """Root coords -> (x, y) relative to the slider, or None if not realized."""
        win = self.da.get_window()
        if win is None:
            return None
        _ok, ox, oy = win.get_origin()
        a = self.da.get_allocation()
        if not self.da.get_has_window():
            ox, oy = ox + a.x, oy + a.y
        return x_root - ox, y_root - oy

    def hit(self, x_root, y_root, pad=6):
        p = self.local(x_root, y_root)
        if p is None or not self.is_visible():
            return None
        x, y = p
        w = self.da.get_allocated_width()
        if -pad <= x < w + pad and -pad <= y < self.h + pad:
            return x
        return None

    def seg_x(self, i, w):
        """Pixel-exact left edge of segment i when n segments fill width w."""
        return round(i * (w + self.gap) / self.n)

    def drag_to(self, x_root, y_root):
        p = self.local(x_root, y_root)
        if p is not None:
            self.from_x(p[0])

    def from_x(self, x):
        # Each segment is one step (100/n %): clicking segment i sets (i+1) steps,
        # so the last segment is always 100%. Left of the first segment = 0%.
        w = self.da.get_allocated_width()
        if x < 0:
            self.set(0, notify=True)
            return
        i = min(self.n - 1, int(x * self.n / max(1, w)))
        self.set((i + 1) * 100 / self.n, notify=True)

    def on_scroll(self, _w, e):
        step = 5 if e.direction == Gdk.ScrollDirection.UP else -5 if e.direction == Gdk.ScrollDirection.DOWN else 0
        if e.direction == Gdk.ScrollDirection.SMOOTH and e.delta_y:
            step = -5 if e.delta_y > 0 else 5
        if step:
            self.set(self.value + step, notify=True)
        return True

    def on_draw(self, _w, cr):
        w = self.da.get_allocated_width()
        filled = round(self.value / 100 * self.n)
        if self.value > 0 and filled == 0:
            filled = 1
        on = C["dim"] if self.muted else C["accent"]
        for i in range(self.n):
            x0 = self.seg_x(i, w)
            sw = self.seg_x(i + 1, w) - self.gap - x0
            if i < filled:
                cr.set_source_rgb(*rgb(on))
                cr.rectangle(x0, 0, sw, self.h)
            else:
                cr.set_source_rgb(*rgb(C["border"]))
                cr.rectangle(x0, self.h // 2 - 2, sw, 4)
            cr.fill()


def pactl_json(what):
    import json
    rc, out, _ = run(["pactl", "-f", "json", "list", what])
    try:
        return json.loads(out) if rc == 0 else []
    except ValueError:
        return []


def vol_pct(dev):
    try:
        ch = next(iter(dev["volume"].values()))
        return int(str(ch["value_percent"]).rstrip("%"))
    except (KeyError, StopIteration, ValueError):
        return 0


class VolumePopup(Popup):
    def __init__(self):
        super().__init__("volume")
        head = Gtk.Box(spacing=10)
        head.pack_start(label("Sound", ("title",)), True, True, 0)
        self.mute_b = button("", self.toggle_mute)
        head.pack_end(self.mute_b, False, False, 0)
        self.frame.pack_start(head, False, False, 0)

        self.big = label("", ("big",))
        self.frame.pack_start(self.big, False, False, 0)
        self.out_slider = PixelSlider(lambda v: self.set_vol("sink", v))
        self.frame.pack_start(self.out_slider, False, False, 6)

        self.mic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        mic_head = Gtk.Box()
        mic_head.pack_start(label("\U000f036c  mic", ("dim",)), True, True, 0)
        self.mic_lbl = label("", ("dim",), 1.0)
        mic_head.pack_end(self.mic_lbl, False, False, 0)
        self.mic_box.pack_start(mic_head, False, False, 0)
        self.mic_slider = PixelSlider(lambda v: self.set_vol("source", v), height=10)
        self.mic_box.pack_start(self.mic_slider, False, False, 4)
        self.frame.pack_start(self.mic_box, False, False, 6)

        self.frame.pack_start(sep(), False, False, 0)
        self.frame.pack_start(label("output", ("dim",)), False, False, 0)
        self.outs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.frame.pack_start(self.outs, False, False, 4)
        self.hint = label("drag, click or scroll the bar", ("dim",))
        self.frame.pack_start(self.hint, False, False, 4)

        self.pending = {}
        self.sinks_sig = None
        self.refresh()
        GLib.timeout_add(1000, self.refresh)

    def refresh(self):
        if self.out_slider.drag or self.mic_slider.drag or self.pending:
            return True
        sinks = pactl_json("sinks")
        _, default, _ = run(["pactl", "get-default-sink"])
        _, dsrc, _ = run(["pactl", "get-default-source"])
        sink = next((x for x in sinks if x.get("name") == default), sinks[0] if sinks else None)
        if sink:
            v, m = vol_pct(sink), bool(sink.get("mute"))
            self.out_slider.muted = m
            self.out_slider.set(v)
            self.big.set_text(f"{v}%" if not m else f"{v}%  muted")
            set_cls(self.big, "dim", m)
            self.mute_b.set_label("\U000f075f muted" if m else "\U000f057e on")
            set_cls(self.mute_b, "sel", not m)
        src = next((x for x in pactl_json("sources") if x.get("name") == dsrc and ".monitor" not in dsrc), None)
        if src:
            v = vol_pct(src)
            self.mic_slider.muted = bool(src.get("mute"))
            self.mic_slider.set(v)
            self.mic_lbl.set_text(f"{v}%" + ("  muted" if src.get("mute") else ""))
        self.mic_box.set_visible(src is not None)

        sig = tuple((x.get("name"), x.get("name") == default) for x in sinks)
        if sig != self.sinks_sig:
            self.sinks_sig = sig
            for ch in self.outs.get_children():
                self.outs.remove(ch)
            for x in sinks:
                active = x.get("name") == default
                desc = x.get("description") or x.get("name")
                desc = desc if len(desc) <= 30 else desc[:29] + "\u2026"
                b = button(("\u25a0 " if active else "\u25a1 ") + desc,
                           lambda n=x.get("name"): self.set_default(n), ("flat",))
                b.get_child().set_xalign(0)
                if active:
                    set_cls(b.get_child(), "accent", True)
                self.outs.pack_start(b, False, False, 0)
            self.outs.show_all()
        return True

    def set_vol(self, kind, v):
        if kind == "sink":
            self.big.set_text(f"{v}%")
        else:
            self.mic_lbl.set_text(f"{v}%")
        first = kind not in self.pending
        self.pending[kind] = v
        if first:  # throttle: apply the latest value at most every 40ms
            GLib.timeout_add(40, self.flush, kind)

    def flush(self, kind):
        v = self.pending.pop(kind, None)
        if v is not None:
            target = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
            subprocess.Popen(["pactl", f"set-{kind}-volume", target, f"{v}%"])
            if kind == "sink" and self.out_slider.muted and v > 0:
                subprocess.Popen(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        return False

    def toggle_mute(self):
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        self.refresh()

    def set_default(self, name):
        run(["pactl", "set-default-sink", name])
        self.sinks_sig = None
        self.refresh()


# =============================================================== power ====
CPUFREQ = "/sys/devices/system/cpu/cpu*/cpufreq"
MODES = [
    # key, label, icon, governor, EPP, power-profiles-daemon name
    ("saver", "Saver", "\U000f032a", "powersave", "power", "power-saver"),
    ("balanced", "Balanced", "\U000f05d1", "powersave", "balance_performance", "balanced"),
    ("performance", "Performance", "\U000f04c5", "performance", "performance", "performance"),
]


def current_mode():
    if shutil.which("powerprofilesctl"):
        _, p, _ = run(["powerprofilesctl", "get"])
        for m in MODES:
            if m[5] == p:
                return m[0]
    gov = read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    epp = read("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference")
    if gov == "performance":
        return "performance"
    if epp in ("power", "balance_power"):
        return "saver"
    return "balanced"


def mode_script(m):
    _k, _l, _i, gov, epp, _p = m
    s = f"for c in {CPUFREQ}; do echo {gov} > $c/scaling_governor; done; "
    if gov != "performance":
        s += f"for c in {CPUFREQ}; do echo {epp} > $c/energy_performance_preference; done"
    return s


BATTERY_LOG = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                           "battery_history")  # written by battery_log.sh: "EPOCH PERCENT STATUS"
BATTERY_SPANS = [3, 12, 24]  # hours the graph can show (click the span button to cycle)


def battery_history(since):
    pts = []
    try:
        with open(BATTERY_LOG) as f:
            for line in f:
                p = line.split(None, 2)
                if len(p) >= 2 and p[0].isdigit() and p[1].isdigit() and int(p[0]) >= since:
                    pts.append((int(p[0]), int(p[1]), p[2].strip() if len(p) > 2 else ""))
    except OSError:
        pass
    pts.sort()
    return pts


def cpu_freqs():
    """(per-cpu current clocks in cpu order, max clock), all in kHz."""
    cur = []
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"),
                       key=lambda p: int(re.search(r"cpu(\d+)/", p).group(1))):
        v = read(path)
        if v.isdigit():
            cur.append(int(v))
    fmax = read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    return cur, int(fmax) if fmax.isdigit() and int(fmax) else 1


def ghz(khz):
    return f"{khz / 1e6:.1f}G"


def battery():
    for b in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        cap = read(f"{b}/capacity", "0")
        st = read(f"{b}/status", "Unknown")
        pw = read(f"{b}/power_now")
        if not pw and read(f"{b}/current_now"):
            pw = str(int(read(f"{b}/current_now")) * int(read(f"{b}/voltage_now", "0")) // 1000000)
        watts = int(pw) / 1e6 if pw.isdigit() else 0.0
        en = read(f"{b}/energy_now") or read(f"{b}/charge_now")
        full = read(f"{b}/energy_full") or read(f"{b}/charge_full")
        left = ""
        if watts > 0.5 and en.isdigit() and full.isdigit():
            if st == "Discharging":
                hrs = int(en) / 1e6 / watts
                left = f"{int(hrs)}h{int(hrs * 60) % 60:02d} left"
            elif st == "Charging":
                hrs = (int(full) - int(en)) / 1e6 / watts
                left = f"{int(hrs)}h{int(hrs * 60) % 60:02d} to full"
        efull_design = read(f"{b}/energy_full_design") or read(f"{b}/charge_full_design")
        health = int(full) / int(efull_design) * 100 if full.isdigit() and efull_design.isdigit() and int(efull_design) else None
        ac = any(read(f"{a}/online") == "1" for a in glob.glob("/sys/class/power_supply/A*"))
        return dict(cap=int(cap), status=st, watts=watts, left=left, health=health,
                    cycles=read(f"{b}/cycle_count"), ac=ac,
                    model=" ".join(x for x in (read(f"{b}/manufacturer"), read(f"{b}/model_name")) if x))
    return None


class PowerPopup(Popup):
    def __init__(self):
        super().__init__("power")
        head = Gtk.Box()
        head.pack_start(label("Power & battery", ("title",)), True, True, 0)
        self.ac_lbl = label("", ("dim",), 1.0)
        head.pack_end(self.ac_lbl, False, False, 0)
        self.frame.pack_start(head, False, False, 0)

        self.big = label("", ("big",), 0.0)
        self.frame.pack_start(self.big, False, False, 0)
        self.state = label("", ("dim",))
        self.frame.pack_start(self.state, False, False, 0)

        g = Gtk.Grid(column_spacing=10, row_spacing=4)
        self.bat_bar, self.bat_lbl = PixelBar(high_good=True), label("", (), 1.0)
        self.draw_bar, self.draw_lbl = PixelBar(), label("", (), 1.0)
        self.health_bar, self.health_lbl = PixelBar(high_good=True), label("", (), 1.0)
        self.freq_bar, self.freq_lbl = PixelBar(), label("", (), 1.0)
        stat_row(g, 0, "batt", self.bat_bar, self.bat_lbl)
        stat_row(g, 1, "draw", self.draw_bar, self.draw_lbl)
        stat_row(g, 2, "health", self.health_bar, self.health_lbl)
        stat_row(g, 3, "freq", self.freq_bar, self.freq_lbl)
        self.frame.pack_start(g, False, False, 8)

        hist = Gtk.Box()
        hist.pack_start(label("history", ("dim",)), True, True, 0)
        self.span_btn = button("", self.next_span, ("flat",))
        hist.pack_end(self.span_btn, False, False, 0)
        self.frame.pack_start(hist, False, False, 0)
        self.graph = BatteryGraph()
        self.frame.pack_start(self.graph, False, False, 2)
        axis = Gtk.Box()
        axis.set_size_request(self.graph.w, -1)
        axis.set_halign(Gtk.Align.START)
        self.axis_l = label("", ("dim",))
        axis.pack_start(self.axis_l, False, False, 0)
        axis.pack_end(label("now", ("dim",), 1.0), False, False, 0)
        self.frame.pack_start(axis, False, False, 0)
        self.hint = label("", ("dim",))
        self.hint.set_line_wrap(True)
        self.hint.set_max_width_chars(30)
        self.hint.set_no_show_all(True)  # only shown while there's no history yet
        self.frame.pack_start(self.hint, False, False, 0)
        self.show_span()
        self.frame.pack_start(sep(), False, False, 0)

        self.info = label("", ("dim",))
        self.frame.pack_start(self.info, False, False, 0)
        self.frame.pack_start(sep(), False, False, 0)

        self.frame.pack_start(label("Mode", ("dim",)), False, False, 0)
        self.btns = {}
        row = Gtk.Box(spacing=8, homogeneous=True)
        for m in MODES:
            b = button(f"{m[2]} {m[1]}", lambda m=m: self.apply(m))
            self.btns[m[0]] = b
            row.pack_start(b, True, True, 0)
        self.frame.pack_start(row, False, False, 6)

        self.auth = Gtk.Box(spacing=6)
        self.pw = Gtk.Entry()
        self.pw.set_visibility(False)
        self.pw.set_placeholder_text("sudo password")
        self.pw.set_hexpand(True)
        self.auth.pack_start(self.pw, True, True, 0)
        self.frame.pack_start(self.auth, False, False, 4)
        self.msg = label("", ("dim",))
        self.msg.set_line_wrap(True)
        self.msg.set_max_width_chars(36)
        self.frame.pack_start(self.msg, False, False, 0)
        self.pending = None
        self.pw.connect("activate", lambda *_: self.apply(self.pending, self.pw.get_text()))

        self.update()
        GLib.timeout_add(1000, self.update)

    def place_and_show(self):
        super().place_and_show()
        self.auth.hide()
        # shrink to the visible content (the window grows again if the password box shows)
        self.resize(self.get_size()[0], 1)

    def show_span(self):
        h = self.graph.hours
        self.span_btn.set_label(f"{h}h ▸")
        self.axis_l.set_text(f"-{h}h")

    def next_span(self):
        i = BATTERY_SPANS.index(self.graph.hours)
        self.graph.hours = BATTERY_SPANS[(i + 1) % len(BATTERY_SPANS)]
        self.show_span()
        self.update()

    def update(self):
        bat = battery()
        self.graph.update((bat["cap"], bat["status"]) if bat else None)
        logged = len(self.graph.points) > 1
        self.hint.set_text("" if logged else "no history yet: battery_log.sh records it once a "
                           "minute (i3 starts it at login)")
        self.hint.set_visible(not logged)
        if bat:
            self.draw_bar.set_value(min(100, bat["watts"] / 45 * 100))
            self.draw_lbl.set_text(f"{bat['watts']:5.1f} W")
            self.bat_bar.set_value(bat["cap"])
            self.bat_lbl.set_text(f"{bat['cap']:3d} %")
            self.big.set_text(f"{bat['cap']}%")
            self.state.set_text(f"{bat['status'].lower()}  {bat['left']}".rstrip())
            self.ac_lbl.set_text("\U000f06a5 AC" if bat["ac"] else "\U000f0079 battery")
            if bat["health"] is not None:
                self.health_bar.set_value(bat["health"])
                self.health_lbl.set_text(f"{bat['health']:3.0f} %")
            extra = [x for x in (bat["model"], f"{bat['cycles']} cycles" if bat["cycles"] else "") if x]
            self.info.set_text("  \u00b7  ".join(extra))
        freqs, fmax = cpu_freqs()
        if freqs:
            avg = sum(freqs) / len(freqs)
            self.freq_bar.set_value(avg / fmax * 100)
            self.freq_lbl.set_text(f"{avg / 1e6:4.1f} GHz")
        cur = current_mode()
        for k, b in self.btns.items():
            set_cls(b, "sel", k == cur)
        return True

    def apply(self, m, password=None):
        if m is None:
            return
        self.pending = m
        self.msg.set_text(f"Switching to {m[1]}…")

        def work():
            if shutil.which("powerprofilesctl"):
                return run(["powerprofilesctl", "set", m[5]])
            if password is not None:
                return run(["sudo", "-S", "-p", "", "sh", "-c", mode_script(m)], inp=password + "\n")
            return run(["sudo", "-n", "sh", "-c", mode_script(m)])

        def done(r):
            self.pw.set_text("")
            if r[0] == 0:
                self.auth.hide()
                self.msg.set_text(f"{m[1]} mode on")
                self.update()
            elif shutil.which("powerprofilesctl"):
                self.msg.set_text(r[2] or "powerprofilesctl failed")
            else:
                self.auth.show_all()
                self.pw.grab_focus()
                wrong = password is not None
                self.msg.set_text("Wrong password, try again" if wrong else
                                  "Needs root: type your password, Enter")

        in_thread(work, done)


# ============================================================= sysinfo ====
def cpu_times():
    out = []
    for line in read("/proc/stat").splitlines():
        if not line.startswith("cpu"):
            break
        v = [int(x) for x in line.split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        out.append((sum(v), idle))
    return out


def meminfo():
    m = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        m[k] = int(v.split()[0]) * 1024
    return m


def cpu_temp():
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{hw}/name") in ("coretemp", "k10temp", "zenpower"):
            t = read(f"{hw}/temp1_input")
            if t.isdigit():
                return int(t) / 1000
    t = read("/sys/class/thermal/thermal_zone0/temp")
    return int(t) / 1000 if t.isdigit() else None


def gib(b):
    return f"{b / 1073741824:.1f}G"


class SysinfoPopup(Popup):
    def __init__(self):
        super().__init__("sysinfo")
        head = Gtk.Box()
        head.pack_start(label("System", ("title",)), True, True, 0)
        self.host = label("", ("dim",), 1.0)
        head.pack_end(self.host, False, False, 0)
        self.frame.pack_start(head, False, False, 0)

        g = Gtk.Grid(column_spacing=10, row_spacing=4)
        self.rows = {}
        for i, key in enumerate(["cpu", "clock", "ram", "swap", "disk", "temp", "batt"]):
            bar = PixelBar(high_good=key == "batt", neutral=key == "clock")
            val, ext = label("", (), 1.0), label("", ("dim",))
            stat_row(g, i, key, bar, val, ext)
            self.rows[key] = (bar, val, ext)
        self.frame.pack_start(g, False, False, 10)
        self.frame.pack_start(sep(), False, False, 0)

        self.frame.pack_start(label("cores", ("dim",)), False, False, 0)
        self.cores = Gtk.Grid(column_spacing=10, row_spacing=2)
        self.core_bars = []
        n = len(cpu_times()) - 1
        for i in range(n):
            bar, val = PixelBar(segments=8, seg_w=5), label("", ("dim",), 1.0)
            clk = label("", ("dim",), 1.0)
            val.set_width_chars(4)
            clk.set_width_chars(4)
            col = (i % 2) * 4
            self.cores.attach(label(f"{i}", ("dim",)), col, i // 2, 1, 1)
            self.cores.attach(bar, col + 1, i // 2, 1, 1)
            self.cores.attach(val, col + 2, i // 2, 1, 1)
            self.cores.attach(clk, col + 3, i // 2, 1, 1)
            self.core_bars.append((bar, val, clk))
        self.frame.pack_start(self.cores, False, False, 6)
        self.frame.pack_start(sep(), False, False, 0)
        self.foot = label("", ("dim",))
        self.frame.pack_start(self.foot, False, False, 0)

        self.prev = cpu_times()
        self.host.set_text(os.uname().nodename)
        GLib.timeout_add(1000, self.update)
        self.update(first=True)

    def put(self, key, pct, value, extra=""):
        bar, val, ext = self.rows[key]
        bar.set_value(pct)
        val.set_text(value)
        ext.set_text(extra)

    def update(self, first=False):
        now = cpu_times()
        usage = []
        for (t1, i1), (t2, i2) in zip(self.prev, now):
            dt = t2 - t1
            usage.append(0.0 if dt <= 0 else (1 - (i2 - i1) / dt) * 100)
        if first:  # no delta yet: use load average as a rough first value
            la = os.getloadavg()[0] / max(1, len(now) - 1) * 100
            usage = [min(100, la)] * len(now)
        self.prev = now
        self.put("cpu", usage[0], f"{usage[0]:3.0f}%")
        freqs, fmax = cpu_freqs()
        for i, ((bar, val, clk), u) in enumerate(zip(self.core_bars, usage[1:])):
            bar.set_value(u)
            val.set_text(f"{u:3.0f}%")
            clk.set_text(ghz(freqs[i]) if i < len(freqs) else "")
        if freqs:
            avg = sum(freqs) / len(freqs)
            self.put("clock", avg / fmax * 100, ghz(avg),
                     f"{min(freqs) / 1e6:.1f}-{max(freqs) / 1e6:.1f}/{ghz(fmax)}")

        m = meminfo()
        used = m["MemTotal"] - m["MemAvailable"]
        self.put("ram", used / m["MemTotal"] * 100, f"{used / m['MemTotal'] * 100:3.0f}%",
                 f"{gib(used)}/{gib(m['MemTotal'])}")
        st = m.get("SwapTotal", 0)
        su = st - m.get("SwapFree", 0)
        self.put("swap", su / st * 100 if st else 0, f"{su / st * 100:3.0f}%" if st else "  -", f"{gib(su)}/{gib(st)}" if st else "none")
        du = shutil.disk_usage("/")
        self.put("disk", du.used / du.total * 100, f"{du.used / du.total * 100:3.0f}%", f"{gib(du.used)}/{gib(du.total)} /")
        t = cpu_temp()
        if t is not None:
            self.put("temp", t, f"{t:3.0f}°", "C")
        bat = battery()
        if bat:
            self.put("batt", bat["cap"], f"{bat['cap']:3d}%", bat["status"].lower())

        up = int(float(read("/proc/uptime", "0").split()[0]))
        la = " ".join(f"{x:.2f}" for x in os.getloadavg())
        self.foot.set_text(f"up {up // 86400}d {up // 3600 % 24}h {up // 60 % 60}m  ·  load {la}\n{os.uname().release}")
        return True


# ============================================================= session ====
class SessionPopup(Popup):
    ACTIONS = [
        ("\U000f033e", "Lock", ["i3lock", "-c", "353E40"], False),
        ("\U000f0343", "Logout", ["i3-msg", "exit"], True),
        ("\U000f04b2", "Suspend", ["systemctl", "hibernate"], True),
        ("\U000f0709", "Reboot", ["systemctl", "reboot"], True),
        ("\U000f0425", "Shutdown", ["systemctl", "poweroff"], True),
    ]

    def __init__(self):
        super().__init__("session")
        self.frame.pack_start(label("Session", ("title",)), False, False, 0)
        _, who, _ = run(["whoami"])
        self.frame.pack_start(label(f"{who}@{os.uname().nodename}", ("dim",)), False, False, 4)
        self.frame.pack_start(sep(), False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.armed = None
        for icon, name, cmd, confirm in self.ACTIONS:
            b = Gtk.Button(label=f"{icon}  {name}")
            b.get_style_context().add_class("flat")
            if confirm:
                b.get_style_context().add_class("danger")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda btn, n=name, c=cmd, cf=confirm, i=icon: self.act(btn, i, n, c, cf))
            box.pack_start(b, False, False, 0)
        self.frame.pack_start(box, False, False, 0)
        self.hint = label("click twice to confirm", ("dim",))
        self.frame.pack_start(self.hint, False, False, 8)

    def act(self, btn, icon, name, cmd, confirm):
        if confirm and self.armed is not btn:
            if self.armed is not None:
                set_cls(self.armed, "armed", False)
                self.armed.set_label(self.armed_text)
            self.armed, self.armed_text = btn, btn.get_label()
            set_cls(btn, "armed", True)
            btn.set_label(f"{icon}  {name}?")
            btn.get_child().set_xalign(0)
            return
        Gdk.Display.get_default().get_default_seat().ungrab()
        self.hide()
        subprocess.Popen(cmd, start_new_session=True)
        GLib.timeout_add(200, lambda: self.quit())


# ============================================================ switcher ====
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import workspaces as wsmod  # noqa: E402

CARD_W = 240
CARDS_PER_ROW = 5


def alt_down():
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    return bool(keymap.get_modifier_state() & Gdk.ModifierType.MOD1_MASK)


def ws_order():
    """Workspaces in ascending order, the focused one, and the previously used one."""
    wss = wsmod.i3("-t", "get_workspaces") or []
    numeric = sorted(wss, key=lambda w: (w["num"] if w["num"] >= 0 else 999, w["name"]))
    cur = next((w for w in wss if w["focused"]), None)
    names = {w["name"]: w for w in numeric}
    prev = next((names[n] for n in wsmod.load_mru() if n in names and (not cur or n != cur["name"])), None)
    return numeric, cur, prev


def pixel_thumb(name, width):
    """Workspace thumbnail, scaled down then up 2x with nearest-neighbour: chunky pixels."""
    try:
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(wsmod.thumb_path(name))
    except Exception:
        return None
    h = max(1, width * pb.get_height() // pb.get_width())
    small = pb.scale_simple(width // 2, h // 2, GdkPixbuf.InterpType.BILINEAR)
    return small.scale_simple(width, h, GdkPixbuf.InterpType.NEAREST)


class EmptyThumb(Gtk.DrawingArea):
    def __init__(self, w, h):
        super().__init__()
        self.set_size_request(w, h)
        self.connect("draw", self.on_draw)

    def on_draw(self, wdg, cr):
        W, H = wdg.get_allocated_width(), wdg.get_allocated_height()
        cr.set_source_rgb(*rgb(C["bg"]))
        cr.paint()
        cr.set_source_rgb(*rgb(C["border"]))
        for y in range(0, H, PIXEL):
            for x in range((y // PIXEL) % 2 * PIXEL, W, PIXEL * 2):
                cr.rectangle(x, y, PIXEL // 2, PIXEL // 2)
        cr.fill()


class SwitcherPopup(Popup):
    def __init__(self, alt_mode=True):
        super().__init__("switcher" if alt_mode else "overview")
        self.alt_mode = alt_mode
        self.done = False
        try:  # fresh thumbnail of where we are now (the overlay isn't up yet)
            wsmod.capture(force=True)
        except Exception:
            pass
        self.items, cur, prev = ws_order()
        wins = wsmod.windows_by_ws()
        cur_i = next((i for i, w in enumerate(self.items) if cur and w["name"] == cur["name"]), 0)
        prev_i = next((i for i, w in enumerate(self.items) if prev and w["name"] == prev["name"]), None)
        # Alt+Tab starts on the workspace you came from (Tab then walks right, wrapping)
        if alt_mode:
            self.sel = prev_i if prev_i is not None else (cur_i + 1) % max(1, len(self.items))
        else:
            self.sel = cur_i

        head = Gtk.Box(spacing=12)
        head.pack_start(label("Workspaces", ("title",)), False, False, 0)
        hint = ("tab / shift+tab to cycle \u00b7 release alt to switch" if alt_mode
                else "click or enter to switch \u00b7 arrows to move \u00b7 esc")
        head.pack_end(label(hint, ("dim",), 1.0), False, False, 0)
        self.frame.pack_start(head, False, False, 0)
        self.frame.pack_start(sep(), False, False, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        self.cards = []
        for i, w in enumerate(self.items):
            card = self.make_card(w, wins.get(w["name"], []), cur and w["name"] == cur["name"])
            card.connect("clicked", lambda _b, i=i: self.commit(i))
            grid.attach(card, i % CARDS_PER_ROW, i // CARDS_PER_ROW, 1, 1)
            self.cards.append(card)
        self.frame.pack_start(grid, False, False, 4)
        self.select(self.sel)

        self.add_events(Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect("key-release-event", self.on_key_release)

    def make_card(self, w, wins, is_cur):
        b = Gtk.Button()
        b.get_style_context().add_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        pb = pixel_thumb(w["name"], CARD_W)
        if pb is not None:
            thumb = Gtk.Image.new_from_pixbuf(pb)
        else:
            thumb = EmptyThumb(CARD_W, CARD_W * 9 // 16)
        frame = Gtk.Box()
        frame.get_style_context().add_class("thumb")
        frame.pack_start(thumb, False, False, 0)
        box.pack_start(frame, False, False, 0)

        top = Gtk.Box(spacing=8)
        top.pack_start(label(w["name"], ("cardname",)), False, False, 0)
        if is_cur:
            top.pack_end(label("\u25a0 here", ("accent",), 1.0), False, False, 0)
        elif w.get("urgent"):
            top.pack_end(label("\u25a0 urgent", ("alert",), 1.0), False, False, 0)
        box.pack_start(top, False, False, 0)

        chars = CARD_W // 9 - 3
        for win in wins[:3]:
            t = win["title"] or win["class"]
            t = t if len(t) <= chars else t[:chars - 1] + "\u2026"
            box.pack_start(label(f"{wsmod.icon_for(win)} {t}", ("dim",)), False, False, 0)
        if len(wins) > 3:
            box.pack_start(label(f"  +{len(wins) - 3} more", ("dim",)), False, False, 0)
        if not wins:
            box.pack_start(label("  empty", ("dim",)), False, False, 0)
        b.add(box)
        return b

    # -- placement: centred on the monitor --------------------------------
    def place_and_show(self):
        self.frame.show_all()
        self.get_child().show()
        self.cover.show()
        _min, nat = self.get_preferred_size()
        display = Gdk.Display.get_default()
        _scr, px, py = display.get_default_seat().get_pointer().get_position()
        mon = display.get_monitor_at_point(px, py).get_geometry()
        self.move(mon.x + (mon.width - nat.width) // 2, mon.y + (mon.height - nat.height) // 3)
        self.show()
        self.anim_start = GLib.get_monotonic_time()
        GLib.timeout_add(16, self.tick)
        self.grab_tries = 0
        GLib.timeout_add(10, self.try_grab)

    def on_grabbed(self):
        # Alt was already let go while we were starting up: behave like a quick Alt+Tab
        if self.alt_mode and not alt_down():
            self.commit()

    # -- selection --------------------------------------------------------
    def select(self, i):
        if not self.cards:
            return
        self.sel = i % len(self.cards)
        for j, c in enumerate(self.cards):
            set_cls(c, "picked", j == self.sel)

    def step(self, d):
        self.select(self.sel + d)

    def commit(self, i=None):
        if self.done or not self.items:
            self.quit()
            return
        self.done = True
        w = self.items[self.sel if i is None else i]
        Gdk.Display.get_default().get_default_seat().ungrab()
        self.hide()
        subprocess.Popen(["i3-msg", "-q", wsmod.ws_cmd(w)], stdout=subprocess.DEVNULL)
        GLib.timeout_add(30, lambda: self.quit())

    def on_key(self, _w, ev):
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self.quit()
        elif k in (Gdk.KEY_Tab, Gdk.KEY_Right, Gdk.KEY_l):
            self.step(1)
        elif k in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Left, Gdk.KEY_h):
            self.step(-1)
        elif k in (Gdk.KEY_Down, Gdk.KEY_j):
            self.step(CARDS_PER_ROW)
        elif k in (Gdk.KEY_Up, Gdk.KEY_k):
            self.step(-CARDS_PER_ROW)
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.commit()
        else:
            ch = chr(Gdk.keyval_to_unicode(k) or 0)
            idx = next((i for i, w in enumerate(self.items) if ch and w["name"] == ch), None)
            if idx is not None:
                self.commit(idx)
        return True

    def on_key_release(self, _w, ev):
        if self.alt_mode and ev.keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
            self.commit()
        return True


def quick_switch():
    """Alt+Tab tapped and released before the overlay could appear: go to the previous workspace."""
    _items, _cur, prev = ws_order()
    if prev:
        subprocess.run(["i3-msg", "-q", wsmod.ws_cmd(prev)], stdout=subprocess.DEVNULL)


# ================================================================ main ====
POPUPS = dict(calendar=CalendarPopup, network=NetworkPopup, volume=VolumePopup, power=PowerPopup,
              sysinfo=SysinfoPopup, session=SessionPopup,
              switcher=lambda: SwitcherPopup(True), overview=lambda: SwitcherPopup(False))
PENDING_TABS = [0]  # Alt+Tab presses that arrive before the switcher window exists


def single_instance(kind):
    """Close any open popup; return True if it was this same kind (toggle off)."""
    try:
        pid_s, old = read(PIDFILE).split()
        pid = int(pid_s)
        os.kill(pid, signal.SIGTERM)
        return old == kind
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    if kind not in POPUPS:
        print(f"usage: {os.path.basename(sys.argv[0])} {{{'|'.join(POPUPS)}}}", file=sys.stderr)
        sys.exit(1)
    if kind == "switcher":
        # A second Alt+Tab while the switcher is starting/open: advance it instead
        try:
            pid_s, old = read(PIDFILE).split()
            if old == "switcher":
                os.kill(int(pid_s), signal.SIGUSR1)
                return
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        signal.signal(signal.SIGUSR1, lambda *_: PENDING_TABS.__setitem__(0, PENDING_TABS[0] + 1))
    if single_instance(kind):
        return
    with open(PIDFILE, "w") as f:
        f.write(f"{os.getpid()} {kind}")

    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-xft-antialias", 0)  # crisp pixel font
    settings.set_property("gtk-xft-hinting", 0)
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_USER)

    if kind == "switcher" and not alt_down():
        quick_switch()
        os.unlink(PIDFILE)
        return

    win = POPUPS[kind]()
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        sig_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        sig_add = GLib.unix_signal_add
    sig_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, win.quit)
    if kind == "switcher":
        win.step(PENDING_TABS[0])
        sig_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (win.step(1), True)[1])
    win.place_and_show()
    Gtk.main()


if __name__ == "__main__":
    main()
