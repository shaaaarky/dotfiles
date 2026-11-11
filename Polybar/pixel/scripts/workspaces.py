#!/usr/bin/env python3
"""Polybar workspace module for i3 (use with tail = true).

Shows every workspace (ascending):
    click      -> switch to that workspace
    scroll     -> previous / next workspace
    right-click-> workspace overview (pixelpop.py overview)

It also feeds the Alt+Tab switcher (pixelpop.py switcher):
    $XDG_RUNTIME_DIR/pixelws/mru.json   most-recently-used workspace order
    $XDG_RUNTIME_DIR/pixelws/<ws>.png   thumbnail of each workspace, taken a
                                        moment after you land on it / it changes
"""
import json
import os
import select
import subprocess
import sys
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf  # noqa: E402

# Colours of the current theme (written by ~/Desktop/dotfiles/Scripts/theme.py)
_C = dict(accent="#8DB38B", bg="#353E40", fg="#d8d2c8", dim="#8a949a", alert="#c96a5f")
try:
    with open(os.path.expanduser("~/Desktop/dotfiles/themes/current/colors")) as _f:
        for _line in _f:
            _k, _eq, _v = _line.strip().partition("=")
            if _eq and _k in _C and len(_v) == 7 and _v.startswith("#"):
                _C[_k] = _v
except OSError:
    pass
ACCENT, BG, FG, DIM, ALERT = (_C[k] for k in ("accent", "bg", "fg", "dim", "alert"))
POP = os.path.expanduser("~/Desktop/dotfiles/Polybar/pixel/scripts/pixelpop.py")
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CACHE = os.path.join(RUN, "pixelws")
POP_PIDFILE = os.path.join(RUN, "pixelpop.pid")
THUMB_W = 480

# (substring of the lowercased WM_CLASS / instance, nerd font glyph)
ICONS = [
    ("firefox", "\U000f0239"), ("librewolf", "\U000f0239"), ("zen", "\U000f0239"),
    ("chrom", "\U000f02af"), ("brave", "\U000f02af"),
    ("claude", "\U000f06a9"),
    ("code", "\U000f0a1e"), ("codium", "\U000f0a1e"),
    ("nvim", ""), ("vim", ""),
    ("terminal", ""), ("kitty", ""), ("alacritty", ""), ("xterm", ""),
    ("urxvt", ""), ("foot", ""), ("wezterm", ""),
    ("discord", "\U000f066f"), ("vesktop", "\U000f066f"), ("telegram", ""),
    ("spotify", "\U000f04c7"), ("vlc", "\U000f057c"), ("mpv", "\U000f040a"),
    ("thunar", "\U000f024b"), ("nautilus", "\U000f024b"), ("pcmanfm", "\U000f024b"), ("dolphin", "\U000f024b"),
    ("gimp", ""), ("steam", ""), ("libreoffice", "\U000f0219"),
    ("zathura", ""), ("evince", ""), ("pavucontrol", "\U000f057e"),
]
DEFAULT_ICON = "\U000f08c6"


def icon_for(win):
    key = f"{win.get('class', '')} {win.get('instance', '')}".lower()
    for sub, glyph in ICONS:
        if sub in key:
            return glyph
    return DEFAULT_ICON


def i3(*args):
    try:
        return json.loads(subprocess.run(["i3-msg", *args], capture_output=True, text=True, timeout=3).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def windows_by_ws():
    """{workspace name: [{'id', 'class', 'instance', 'title', 'focused', 'urgent'}]}"""
    out = {}
    tree = i3("-t", "get_tree")

    def walk(n, ws):
        if n.get("type") == "workspace":
            ws = n.get("name")
            out.setdefault(ws, [])
        if n.get("window") and ws and ws != "__i3_scratch":
            p = n.get("window_properties") or {}
            out[ws].append(dict(id=n["id"], cls=p.get("class", ""), instance=p.get("instance", ""),
                                title=n.get("name") or "", focused=n.get("focused", False),
                                urgent=n.get("urgent", False), **{"class": p.get("class", "")}))
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            walk(c, ws)

    if tree:
        walk(tree, None)
    return out


def ws_cmd(ws):
    if ws.get("num", -1) >= 0 and str(ws["num"]) == ws["name"]:
        return f"workspace number {ws['num']}"
    return "workspace " + ws["name"].replace(":", "\\:")


# ------------------------------------------------------------ rendering ----
def render():
    wss = i3("-t", "get_workspaces") or []
    parts = []
    for ws in sorted(wss, key=lambda w: (w["num"] if w["num"] >= 0 else 999, w["name"])):
        body = ws["name"].replace("%", "%%")
        if ws["focused"]:
            seg = f"%{{B{ACCENT}}}%{{F{BG}}}  {body}  %{{F-}}%{{B-}}"
        elif ws["urgent"]:
            seg = f"%{{B{ALERT}}}%{{F{BG}}}  {body}  %{{F-}}%{{B-}}"
        elif ws["visible"]:
            seg = f"%{{u{ACCENT}}}%{{+u}}  {body}  %{{-u}}"
        else:
            seg = f"  %{{F{FG}}}{body}%{{F-}}  "
        parts.append(f"%{{A1:i3-msg -q {ws_cmd(ws)}:}}{seg}%{{A}}")
    line = "".join(parts)
    # scroll anywhere on the module, right-click for the overview
    line = (f"%{{A4:i3-msg -q workspace prev_on_output:}}%{{A5:i3-msg -q workspace next_on_output:}}"
            f"%{{A3:{POP} overview &:}}{line}%{{A}}%{{A}}%{{A}}")
    print(line, flush=True)
    return wss


# ------------------------------------------------------------------ MRU ----
def save_json(name, data):
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, f".{name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(CACHE, name))


def load_mru():
    try:
        with open(os.path.join(CACHE, "mru.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def touch_mru(mru, name):
    if name in mru:
        mru.remove(name)
    mru.insert(0, name)
    del mru[30:]
    save_json("mru.json", mru)


# ----------------------------------------------------------- thumbnails ----
def popup_open():
    try:
        os.kill(int(open(POP_PIDFILE).read().split()[0]), 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


def thumb_path(name):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return os.path.join(CACHE, f"ws_{safe}.png")


def capture(force=False):
    """Screenshot the focused workspace area into the thumbnail cache."""
    if not force and popup_open():  # don't capture our own popups
        return
    ws = next((w for w in i3("-t", "get_workspaces") or [] if w["focused"]), None)
    if not ws:
        return
    r = ws["rect"]
    root = Gdk.get_default_root_window()
    pb = Gdk.pixbuf_get_from_window(root, r["x"], r["y"], r["width"], r["height"])
    if pb is None:
        return
    h = max(1, THUMB_W * r["height"] // r["width"])
    pb = pb.scale_simple(THUMB_W, h, GdkPixbuf.InterpType.BILINEAR)
    os.makedirs(CACHE, exist_ok=True)
    tmp = thumb_path(ws["name"]) + ".tmp"
    pb.savev(tmp, "png", [], [])
    os.replace(tmp, thumb_path(ws["name"]))


# ----------------------------------------------------------------- main ----
def events():
    """Yield i3 workspace/window events (re-subscribes if i3 restarts)."""
    dec = json.JSONDecoder()
    while True:
        p = subprocess.Popen(["i3-msg", "-t", "subscribe", "-m", '["workspace","window","output"]'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        buf = ""
        fd = p.stdout.fileno()
        while True:
            yield None  # gives the caller a chance to run timers
            r, _, _ = select.select([fd], [], [], 0.25)
            if not r:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk.decode(errors="replace")
            while True:
                s = buf.lstrip()
                if not s:
                    buf = ""
                    break
                try:
                    ev, end = dec.raw_decode(s)
                except ValueError:
                    break
                buf = s[end:]
                yield ev
        p.wait()
        time.sleep(1)


def main():
    os.makedirs(CACHE, exist_ok=True)
    mru = load_mru()
    wss = render()
    cur = next((w["name"] for w in wss if w["focused"]), None)
    if cur:
        touch_mru(mru, cur)
    capture_at = time.monotonic() + 1.0

    for ev in events():
        now = time.monotonic()
        if isinstance(ev, dict):
            change = ev.get("change")
            if "current" in ev and change == "focus" and ev["current"]:
                touch_mru(mru, ev["current"]["name"])
                capture_at = now + 0.6  # let the new workspace paint first
            elif change in ("new", "close", "move", "title", "fullscreen_mode", "floating"):
                capture_at = min(capture_at or now + 1.5, now + 1.5)
            if change != "title":
                render()
        if capture_at and now >= capture_at:
            capture_at = None
            try:
                capture()
            except Exception as e:  # never let a screenshot kill the bar module
                print(f"capture failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
