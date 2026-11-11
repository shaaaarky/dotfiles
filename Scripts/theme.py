#!/usr/bin/env python3
"""theme.py: switch the colour theme of the terminal, i3, polybar and the wallpaper.

    theme.py               pick a theme from a menu (rofi, falls back to zenity)
    theme.py NAME          apply themes/NAME.theme
    theme.py list          list the themes (* = current)
    theme.py current       print the current theme's name
    theme.py reapply       apply the current theme again (after editing its file)
    theme.py check [NAME]  validate theme files without applying anything
    theme.py wallpaper     set the current theme's wallpaper (i3 runs this at login)

Themes are plain text files: ~/Desktop/dotfiles/themes/NAME.theme
(copy moss.theme to start a new one). Wallpapers are looked up in
~/Desktop/Wallpapers (override with $THEME_WALLPAPERS), or give a full path.

What a switch changes:
    terminal   xfce4-terminal colours (open terminals update live)
    rofi       colours of the launcher + menus <- themes/current/rofi.rasi (via themes/rofi.rasi)
    i3         window border colours        <- themes/current/i3.conf (include'd by i3/config)
    polybar    every bar config's [colors]  <- themes/current/polybar.ini (include-file)
    popups     pixelpop.py, workspaces.py, network_speed_icon.sh <- themes/current/colors
    wallpaper  feh                          <- themes/current/wallpaper (symlink, used at login)

Everything in themes/current/ is generated: edit the .theme file instead.
"""
import hashlib
import html
import os
import re
import shutil
import signal
import subprocess
import sys

DOTFILES = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # Scripts/ lives one level down
SCRIPTS = os.path.join(DOTFILES, "Scripts")
THEMES = os.path.join(DOTFILES, "themes")
CURRENT = os.path.join(THEMES, "current")
WALLPAPERS = os.path.expanduser(os.environ.get("THEME_WALLPAPERS", "~/Desktop/Wallpapers"))
POLYBAR_CHOOSER = os.path.join(SCRIPTS, "choose_polybar.sh")
POPUP_PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pixelpop.pid")

UI_KEYS = ["bg", "bg_alt", "bg_hi", "border", "fg", "dim", "accent", "warn", "alert"]
ANSI_KEYS = [f"color{i}" for i in range(16)]
OPTIONAL_COLORS = ["term_bg", "term_fg", "cursor", "selection", "indicator"]
DEFAULTABLE = ["cursor", "selection"]  # "default" = xfce4-terminal's own colour
TEXT_KEYS = ["name", "wallpaper", "wallpaper_mode"]
WALLPAPER_MODES = ["fill", "center", "max", "scale", "tile"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeError(Exception):
    pass


# ------------------------------------------------------------ theme files --
def theme_path(name):
    return os.path.join(THEMES, name + ".theme")


def theme_names():
    return sorted(f[:-6] for f in os.listdir(THEMES) if f.endswith(".theme"))


def current_name():
    try:
        with open(os.path.join(CURRENT, "name")) as f:
            return f.read().strip()
    except OSError:
        return ""


def parse(name):
    """Read themes/NAME.theme -> dict. Lines are `key = value`; `#` starts a
    comment line; anything after the value (e.g. a note) is ignored for colours."""
    path = theme_path(name)
    if not os.path.isfile(path):
        raise ThemeError(f"no theme '{name}' (looked for {path})")
    t, errors = {}, []
    with open(path) as f:
        for n, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            pairs = re.findall(r"(\w+)\s*=\s*(#[0-9a-fA-F]{6})\b", line)
            if len(pairs) > 1:  # several colours on one line: color0 = #.. color8 = #..
                for key, val in pairs:
                    if key not in ANSI_KEYS + UI_KEYS + OPTIONAL_COLORS:
                        errors.append(f"line {n}: unknown key '{key}'")
                    t[key] = val.lower()
                continue
            key, eq, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if not eq or not key:
                errors.append(f"line {n}: expected `key = value`")
                continue
            if key in TEXT_KEYS:
                t[key] = val
            elif key in UI_KEYS + ANSI_KEYS + OPTIONAL_COLORS:
                val = val.split()[0] if val else ""
                if key in DEFAULTABLE and val == "default":
                    t[key] = val
                    continue
                if not HEX.match(val):
                    errors.append(f"line {n}: {key} = '{val}' is not a #rrggbb colour")
                t[key] = val.lower()
            else:
                errors.append(f"line {n}: unknown key '{key}'")
    missing = [k for k in UI_KEYS + ANSI_KEYS if k not in t]
    if missing:
        errors.append("missing: " + ", ".join(missing))
    mode = t.setdefault("wallpaper_mode", "fill")
    if mode not in WALLPAPER_MODES:
        errors.append(f"wallpaper_mode '{mode}': use one of {', '.join(WALLPAPER_MODES)}")
    if t.get("wallpaper") and not wallpaper_file(t):
        errors.append(f"wallpaper '{t['wallpaper']}' not found in {WALLPAPERS}")
    if errors:
        raise ThemeError(f"{path}:\n  " + "\n  ".join(errors))
    t.setdefault("name", name)
    t.setdefault("term_bg", t["bg"])
    t.setdefault("term_fg", t["fg"])
    t.setdefault("cursor", t["accent"])
    t.setdefault("selection", t["border"])
    t.setdefault("indicator", t["color6"])
    return t


def wallpaper_file(t):
    w = os.path.expanduser(t.get("wallpaper", ""))
    if not w:
        return None
    path = w if os.path.isabs(w) else os.path.join(WALLPAPERS, w)
    return path if os.path.isfile(path) else None


# -------------------------------------------------------------- generate --
def generated(t, slug, comment="#"):
    return f"{comment} generated by theme.py from themes/{slug}.theme. Don't edit: switch themes instead.\n"


def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def generate(slug, t):
    os.makedirs(CURRENT, exist_ok=True)

    # shell-sourceable and trivial to parse from python
    write(os.path.join(CURRENT, "colors"), generated(t, slug) + "".join(
        f"{k}={t[k]}\n" for k in UI_KEYS + ANSI_KEYS + OPTIONAL_COLORS))

    # one [colors] section that covers the keys of all three polybar configs
    pb = dict(background=t["bg"], background_alt=t["bg_alt"], border=t["border"],
              foreground=t["fg"], primary=t["accent"], secondary=t["accent"],
              alert=t["alert"], warn=t["warn"], warning=t["warn"], disabled=t["dim"],
              red=t["alert"], urgent=t["alert"], success=t["accent"], blue=t["color4"])
    write(os.path.join(CURRENT, "polybar.ini"), generated(t, slug, ";") + "[colors]\n" + "".join(
        f"{k.replace('_', '-')} = {v}\n" for k, v in pb.items()))

    rows = [  # class, border, background, text, indicator, child_border
        ("client.focused", t["accent"], t["bg_alt"], t["fg"], t["indicator"], t["accent"]),
        ("client.focused_inactive", t["border"], t["bg"], t["fg"], t["border"], t["border"]),
        ("client.unfocused", t["bg"], t["bg"], t["dim"], t["bg"], t["bg"]),
        ("client.urgent", t["alert"], t["alert"], t["bg"], t["alert"], t["alert"]),
        ("client.placeholder", t["bg"], t["bg"], t["fg"], t["bg"], t["bg"]),
    ]
    write(os.path.join(CURRENT, "i3.conf"), generated(t, slug)
          + "# class                  border   backgr.  text     indicator child_border\n"
          + "".join(f"{r[0]:<24} " + "  ".join(r[1:]) + "\n" for r in rows)
          + f"client.background        {t['bg']}\n")

    # rofi: themes/rofi.rasi (the layout) @imports these as @th-bg, @th-accent, ...
    write(os.path.join(CURRENT, "rofi.rasi"), generated(t, slug, "//") + "* {\n" + "".join(
        f"    th-{k.replace('_', '-')}: {t[k]};\n" for k in UI_KEYS) + "}\n")

    link = os.path.join(CURRENT, "wallpaper")
    wp = wallpaper_file(t)
    if os.path.lexists(link):
        os.unlink(link)
    if wp:
        os.symlink(wp, link)
    write(os.path.join(CURRENT, "wallpaper_mode"), t["wallpaper_mode"] + "\n")
    write(os.path.join(CURRENT, "name"), slug + "\n")


# ----------------------------------------------------------------- apply --
def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def apply_terminal(t):
    if not shutil.which("xfconf-query"):
        return "skipped (xfconf-query not found)"
    props = {
        "color-background": t["term_bg"],
        "color-foreground": t["term_fg"],
        "color-palette": ";".join(t[k] for k in ANSI_KEYS),
        "color-bold-use-default": "true",
    }
    if t["cursor"] == "default":
        props["color-cursor-use-default"] = "true"
    else:
        props.update({"color-cursor-use-default": "false", "color-cursor": t["cursor"],
                      "color-cursor-foreground": t["term_bg"]})
    if t["selection"] == "default":
        props["color-selection-use-default"] = "true"
    else:
        props.update({"color-selection-use-default": "false", "color-selection": t["term_fg"],
                      "color-selection-background": t["selection"]})
    bad = []
    for prop, val in props.items():
        typ = "bool" if val in ("true", "false") else "string"
        r = run(["xfconf-query", "-c", "xfce4-terminal", "-p", "/" + prop, "-n", "-t", typ, "-s", val])
        if r.returncode:
            bad.append(prop)
    return f"failed: {', '.join(bad)}" if bad else "ok"


def apply_wallpaper(t):
    wp = wallpaper_file(t)
    if not wp:
        return "unchanged (theme has no wallpaper)"
    cmd = ["feh", f"--bg-{t['wallpaper_mode']}", "--image-bg", t["bg"], wp]
    r = run(cmd)
    return "ok" if r.returncode == 0 else f"failed: {r.stderr.strip()}"


def close_popups():
    """Open pixelpop popups read their colours at start: close them."""
    try:
        with open(POPUP_PIDFILE) as f:
            os.kill(int(f.read().split()[0]), signal.SIGTERM)
    except (OSError, ValueError, IndexError):
        pass


def apply_i3():
    r = run(["i3-msg", "-t", "command", "reload"])  # re-reads themes/current/i3.conf
    if r.returncode == 0 and '"success":true' in r.stdout.replace(" ", ""):
        return "ok"
    return f"not reloaded ({(r.stderr or r.stdout).strip() or 'is i3 running?'})"


def apply_bar():
    """Bars started with --reload (choose_polybar.sh does that) watch their
    included files and reload by themselves when polybar.ini changes, which
    also restarts their scripts. Any other bar gets restarted over IPC."""
    pids = run(["pgrep", "-x", "polybar"]).stdout.split()
    if not pids:
        return "no bar running"
    restarted = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if "--reload" in args or "-r" in args:
            continue
        if run(["polybar-msg", "-p", pid, "cmd", "restart"]).returncode == 0:
            restarted += 1
        else:  # no IPC: relaunch the last chosen bar
            subprocess.Popen([POLYBAR_CHOOSER, "--last"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "ok (relaunched)"
    return "ok (restarted)" if restarted else "ok (reloads itself)"


def apply(name):
    t = parse(name)
    generate(name, t)
    close_popups()
    print(f"theme: {name}")
    print(f"  terminal   {apply_terminal(t)}")
    print(f"  wallpaper  {apply_wallpaper(t)}")
    print(f"  i3         {apply_i3()}")
    print(f"  bar        {apply_bar()}")


# ------------------------------------------------------------------ menu --
THUMB_W, THUMB_H = 128, 72
SCREEN_W = 1920  # used to scale `center` wallpapers in the preview


def thumbnail(slug, t):
    """Small preview of the theme's wallpaper (cached), or None without Pillow."""
    wp = wallpaper_file(t)
    if not wp:
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "theme.py")
    key = f"{wp}|{os.path.getmtime(wp)}|{t['wallpaper_mode']}|{t['bg']}|{THUMB_W}"
    out = os.path.join(cache, f"{slug}-{hashlib.md5(key.encode()).hexdigest()[:10]}.png")
    if os.path.exists(out):
        return out
    os.makedirs(cache, exist_ok=True)
    for old in os.listdir(cache):  # previews of this theme's old wallpaper
        if old.startswith(slug + "-") and old.endswith(".png"):
            os.unlink(os.path.join(cache, old))
    try:
        with Image.open(wp) as im:
            im = im.convert("RGB")
            mode = t["wallpaper_mode"]
            if mode == "scale":
                th = im.resize((THUMB_W, THUMB_H))
            elif mode in ("fill", "tile"):
                th = ImageOps.fit(im, (THUMB_W, THUMB_H))
            else:  # center / max: on the theme's background, like feh --image-bg
                th = Image.new("RGB", (THUMB_W, THUMB_H), t["bg"])
                if mode == "max":
                    im = ImageOps.contain(im, (THUMB_W, THUMB_H))
                else:
                    f = THUMB_W / SCREEN_W
                    im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))))
                th.paste(im, ((THUMB_W - im.width) // 2, (THUMB_H - im.height) // 2))
            th.save(out)
    except OSError:
        return None
    return out


def preview_row(slug, t, cur):
    """One menu row (pango markup): name, desktop colours on the theme's own
    background, then the 16 terminal colours on the terminal background."""
    def cell(fg, bg, text):
        return f'<span foreground="{fg}" background="{bg}">{text}</span>'

    mark = "●" if slug == cur else " "
    desk = cell(t["fg"], t["bg"], " Aa ") + "".join(
        cell(t[k], t["bg"], "██") + cell(t["bg"], t["bg"], " ")
        for k in ("accent", "warn", "alert", "dim", "border"))
    tb = t["term_bg"]
    term = (cell(tb, tb, " ") + "".join(cell(t[f"color{i}"], tb, "█") for i in range(8))
            + cell(tb, tb, " ") + "".join(cell(t[f"color{i}"], tb, "█") for i in range(8, 16))
            + cell(tb, tb, " "))
    return f"{mark} {html.escape(slug.ljust(10))}  {desk}  {term}"


def menu():
    names, cur = theme_names(), current_name()
    rows = []
    for n in names:
        try:
            t = parse(n)
        except ThemeError:
            rows.append(f"  {html.escape(n.ljust(10))}  <i>invalid: run theme.py check</i>")
            continue
        icon = thumbnail(n, t)
        rows.append(preview_row(n, t, cur) + (f"\0icon\x1f{icon}" if icon else ""))
    if shutil.which("rofi"):
        cmd = ["rofi", "-dmenu", "-i", "-p", "theme", "-no-custom", "-format", "i",
               "-markup-rows", "-show-icons",
               "-theme-str", f"window {{ width: 900px; }} listview {{ lines: {max(1, len(names))}; }} "
                             f"element-icon {{ size: {THUMB_W // 2 + 8}px; }}"]
        if cur in names:
            cmd += ["-selected-row", str(names.index(cur))]
        r = subprocess.run(cmd, input="\n".join(rows), capture_output=True, text=True)
        pick = r.stdout.strip()
        return names[int(pick)] if pick.isdigit() else None
    if shutil.which("zenity"):
        r = subprocess.run(["zenity", "--list", "--title=Theme", "--column=Theme", *names],
                           capture_output=True, text=True)
        return r.stdout.strip() or None
    raise ThemeError("no menu program (install rofi or zenity), or run: theme.py NAME")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd in ("-h", "--help", "help"):
            print(__doc__.strip())
        elif cmd == "list":
            cur = current_name()
            for n in theme_names():
                print(("* " if n == cur else "  ") + n)
        elif cmd == "current":
            print(current_name() or "(none)")
        elif cmd == "check":
            names = argv[2:] or theme_names()
            failed = 0
            for n in names:
                try:
                    parse(n)
                    print(f"ok    {n}")
                except ThemeError as e:
                    failed += 1
                    print(f"FAIL  {e}")
            return 1 if failed else 0
        elif cmd == "wallpaper":  # i3 runs this at login
            if not current_name():
                raise ThemeError("no theme applied yet")
            print(f"wallpaper: {apply_wallpaper(parse(current_name()))}")
        elif cmd == "reapply":
            if not current_name():
                raise ThemeError("no theme applied yet")
            apply(current_name())
        elif cmd == "":
            pick = menu()
            if pick:
                apply(pick)
        else:
            apply(cmd)
    except ThemeError as e:
        print(f"theme.py: {e}", file=sys.stderr)
        if cmd == "" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "theme.py", str(e)])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
