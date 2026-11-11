#!/usr/bin/env python3
"""script_launcher.py: search and run the scripts in this folder (Mod4+x).

Everything it shows comes from the "## Scripts" section of ../README.md:
    ### NAME             one entry per script
    prose                the explanation (first sentence = the short line in the list)
    ```sh ... ```        the commands you can pick; "# text" after a command is its hint
    <!-- launcher: terminal -->   run this script in a terminal by default

Scripts you run often float to the top, and so do their most-used commands.

Keys:  type to search · Up/Down pick a script · Tab/Shift+Tab pick a command
       Enter run · Shift+Enter run in a terminal · Ctrl+E edit the command · Esc close
Commands without a terminal run in the background; any output (or a failure)
shows up as a notification. Running the launcher again while it's open closes it.
"""
import html
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

SCRIPTS = os.path.dirname(os.path.realpath(__file__))
DOTFILES = os.path.dirname(SCRIPTS)
README = os.path.join(DOTFILES, "README.md")
THEME_COLORS = os.path.join(DOTFILES, "themes", "current", "colors")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                     "script_launcher.json")
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "script_launcher.pid")
SELF = os.path.basename(__file__)


# ---------------------------------------------------------------- theme ----
def theme_colors(defaults):
    """The current theme's colours (written by theme.py), else defaults."""
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


C = theme_colors(dict(bg="#353E40", bg_alt="#3d474a", bg_hi="#43504f", border="#4a5659",
                      fg="#d8d2c8", dim="#8a949a", accent="#8DB38B", warn="#d8a657",
                      alert="#c96a5f"))
FONT = "Terminus"
FONT_PX = 18
SMALL_PX = 16
BIG_PX = 28

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
window, #frame, list, row, scrolledwindow, viewport {{ background-color: {C['bg']}; }}
#frame {{ border: 2px solid {C['border']}; padding: 10px 14px 14px 14px; }}
.title {{ color: {C['accent']}; }}
.big {{ font-size: {BIG_PX}px; }}
.small {{ font-size: {SMALL_PX}px; }}
.dim {{ color: {C['dim']}; }}
.accent {{ color: {C['accent']}; }}
.warn {{ color: {C['warn']}; }}
.sep {{ background-color: {C['border']}; min-height: 2px; min-width: 2px; }}
row {{ padding: 3px 8px; border: 2px solid transparent; }}
row:hover {{ background-color: {C['bg_alt']}; }}
row:selected, row:selected:hover {{ background-color: {C['bg_hi']}; border-color: {C['accent']}; }}
row:selected .name {{ color: {C['accent']}; }}
button {{
    background-color: {C['bg_alt']};
    border: 2px solid {C['border']};
    padding: 1px 10px;
    min-height: 0;
    min-width: 0;
}}
button:hover {{ border-color: {C['accent']}; }}
button:hover label {{ color: {C['accent']}; }}
button.sel {{ background-color: {C['accent']}; border-color: {C['accent']}; }}
button.sel label {{ color: {C['bg']}; }}
entry {{
    background-color: {C['bg_alt']};
    border: 2px solid {C['border']};
    padding: 3px 8px;
    caret-color: {C['accent']};
}}
entry:focus {{ border-color: {C['accent']}; }}
entry selection {{ background-color: {C['accent']}; color: {C['bg']}; }}
scrollbar, scrollbar slider {{ background-color: {C['bg']}; border: 0; min-width: 4px; }}
scrollbar slider {{ background-color: {C['border']}; }}
"""


# --------------------------------------------------------------- readme ----
class Script:
    def __init__(self, name, order):
        self.name = name
        self.order = order
        self.paragraphs = []   # prose, markdown
        self.commands = []     # [(command, hint)]
        self.terminal = False

    @property
    def short(self):
        text = self.paragraphs[0] if self.paragraphs else ""
        m = re.match(r"(.+?[.!?])(\s|$)", text)
        return strip_md(m.group(1) if m else text)

    def haystack(self):
        parts = [self.name, *self.paragraphs] + [f"{c} {h}" for c, h in self.commands]
        return " ".join(parts).lower()


def parse_readme(path=README):
    """The "## Scripts" section of the README -> [Script]."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    scripts, cur, in_section, in_code, para = [], None, False, False, []

    def flush():
        if cur is not None and para:
            cur.paragraphs.append(" ".join(para))
        para.clear()

    for line in lines:
        if line.startswith("## "):
            flush()
            in_section = line[3:].strip().lower() == "scripts"
            cur = None
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            flush()
            cur = Script(line[4:].strip(), len(scripts))
            scripts.append(cur)
            continue
        if cur is None:
            continue
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            cmd, _, hint = line.partition("  #")
            if cmd.strip():
                cur.commands.append((cmd.strip(), hint.strip()))
            continue
        tag = re.fullmatch(r"\s*<!--\s*launcher:\s*(.*?)\s*-->\s*", line)
        if tag:
            cur.terminal = "terminal" in tag.group(1).split()
            continue
        if line.strip():
            para.append(line.strip())
        else:
            flush()
    flush()

    scripts = [s for s in scripts if s.name != SELF]
    for s in scripts:
        if not s.commands:
            s.commands.append((s.name, "run it"))
    return scripts


def strip_md(text):
    return re.sub(r"\*\*(.+?)\*\*|`([^`]+)`", lambda m: m.group(1) or m.group(2), text)


def md_markup(text):
    """Tiny markdown -> Pango: `code` in the accent colour, **bold**."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", rf'<span foreground="{C["accent"]}">\1</span>', out)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


# ---------------------------------------------------------------- usage ----
def load_usage():
    try:
        with open(STATE) as f:
            d = json.load(f)
        return dict(scripts=dict(d.get("scripts", {})), commands=dict(d.get("commands", {})))
    except (OSError, ValueError, AttributeError):
        return dict(scripts={}, commands={})


def save_usage(usage):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(usage, f, indent=1, sort_keys=True)
        os.replace(tmp, STATE)
    except OSError:
        pass


# -------------------------------------------------------------- running ----
NOTIFY_WRAPPER = r'''
out=$(bash -c "$1" 2>&1 </dev/null); rc=$?
if [ $rc -ne 0 ]; then
    notify-send -a Scripts -u critical "$2 failed (exit $rc)" "$(printf '%s' "$out" | tail -c 900)"
elif [ -n "$out" ]; then
    notify-send -a Scripts "$2" "$(printf '%s' "$out" | tail -c 900)"
fi
'''


def expand(cmdline, names):
    """Bare script names -> full paths, so they also work after sudo (which resets PATH)."""
    for n in sorted(names, key=len, reverse=True):
        path = shlex.quote(os.path.join(SCRIPTS, n))
        cmdline = re.sub(rf"(?<![\w./-]){re.escape(n)}(?![\w.-])", lambda _m: path, cmdline)
    return cmdline


def terminal_argv(title, shell_cmd):
    if shutil.which("xfce4-terminal"):
        return ["xfce4-terminal", "--hold", "-T", title, "-x", "bash", "-c", shell_cmd]
    term = os.environ.get("TERMINAL") or shutil.which("x-terminal-emulator") or "xterm"
    return [term, "-e", "bash", "-c", shell_cmd + '; echo; read -rp "[done, Enter to close]"']


def launch(cmdline, names, terminal):
    env = dict(os.environ, PATH=SCRIPTS + os.pathsep + os.environ.get("PATH", ""))
    full = expand(cmdline, names)
    if terminal:
        argv = terminal_argv(cmdline, full)
    else:
        argv = ["bash", "-c", NOTIFY_WRAPPER, "script_launcher", full, cmdline]
    subprocess.Popen(argv, env=env, cwd=os.path.expanduser("~"), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------- ui ----
def label(text="", cls=(), xalign=0.0, markup=False, wrap=False):
    lb = Gtk.Label()
    lb.set_markup(text) if markup else lb.set_text(text)
    lb.set_xalign(xalign)
    if wrap:
        lb.set_line_wrap(True)
        lb.set_max_width_chars(1)  # let the container decide the width
    for c in cls:
        lb.get_style_context().add_class(c)
    return lb


def sep(vertical=False):
    s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL if vertical
                      else Gtk.Orientation.HORIZONTAL)
    s.get_style_context().add_class("sep")
    return s


class Launcher(Gtk.Window):
    def __init__(self):
        super().__init__(title="Scripts")
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(980, 580)
        self.set_decorated(False)
        self.connect("key-press-event", self.on_key)
        self.connect("focus-out-event", self.on_focus_out)
        self.connect("delete-event", self.quit)
        self.had_focus = False

        self.scripts = parse_readme()
        self.usage = load_usage()
        self.names = {s.name for s in self.scripts} | {
            f for f in os.listdir(SCRIPTS) if os.path.isfile(os.path.join(SCRIPTS, f))}
        self.visible = []
        self.cmd_rows = []
        self.current = None

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_name("frame")
        self.add(frame)

        head = Gtk.Box(spacing=12)
        head.pack_start(label("▌scripts", ("title", "big")), False, False, 0)
        head.pack_end(label("enter run · shift+enter terminal · tab command · ctrl+e edit · esc close",
                            ("dim", "small")), False, False, 0)
        frame.pack_start(head, False, False, 0)

        self.search = Gtk.Entry()
        self.search.set_placeholder_text("search: name, what it does, a command…")
        self.search.connect("changed", lambda *_: self.refilter())
        frame.pack_start(self.search, False, False, 0)

        body = Gtk.Box(spacing=12)
        frame.pack_start(body, True, True, 0)

        # left: the scripts
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.list.connect("row-selected", self.on_script_selected)
        self.list.connect("row-activated", lambda *_: self.run_current(False))
        self.list.set_can_focus(False)
        left = Gtk.ScrolledWindow()
        left.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left.set_size_request(330, -1)
        left.add(self.list)
        body.pack_start(left, False, False, 0)
        body.pack_start(sep(vertical=True), False, False, 0)

        # right: the selected script's explanation + commands
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.title = label("", ("title", "big"))
        self.mode = label("", ("dim", "small"))
        trow = Gtk.Box(spacing=12)
        trow.pack_start(self.title, False, False, 0)
        trow.pack_end(self.mode, False, False, 0)
        right.pack_start(trow, False, False, 0)
        self.desc = label("", wrap=True, markup=True)
        self.desc.set_valign(Gtk.Align.START)
        right.pack_start(self.desc, False, False, 0)
        right.pack_start(sep(), False, False, 2)
        right.pack_start(label("commands", ("dim", "small")), False, False, 0)
        self.cmds = Gtk.ListBox()
        self.cmds.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.cmds.set_can_focus(False)
        self.cmds.connect("row-selected", self.on_cmd_selected)
        self.cmds.connect("row-activated", lambda *_: self.run_current(False))
        cscroll = Gtk.ScrolledWindow()
        cscroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        cscroll.add(self.cmds)
        right.pack_start(cscroll, True, True, 0)
        body.pack_start(right, True, True, 0)

        # bottom: the command that Enter runs (editable)
        bottom = Gtk.Box(spacing=8)
        bottom.pack_start(label("$", ("accent",)), False, False, 0)
        self.cmdline = Gtk.Entry()
        self.cmdline.connect("activate", lambda *_: self.run_current(False))
        bottom.pack_start(self.cmdline, True, True, 0)
        run_btn = Gtk.Button(label="run")
        run_btn.get_style_context().add_class("sel")
        run_btn.connect("clicked", lambda *_: self.run_current(False))
        term_btn = Gtk.Button(label="terminal")
        term_btn.connect("clicked", lambda *_: self.run_current(True))
        bottom.pack_start(run_btn, False, False, 0)
        bottom.pack_start(term_btn, False, False, 0)
        frame.pack_start(bottom, False, False, 0)

        if not self.scripts:
            self.title.set_text("no scripts")
            self.desc.set_text(f"Couldn't find a \"## Scripts\" section with \"### name\" "
                               f"entries in {README}.")
        self.refilter()
        self.search.grab_focus()

    # -- data ----------------------------------------------------------------
    def script_uses(self, s):
        return self.usage["scripts"].get(s.name, 0)

    def cmd_uses(self, cmd):
        return self.usage["commands"].get(cmd, 0)

    def ranked(self, query):
        words = query.lower().split()
        out = []
        for s in self.scripts:
            hay = s.haystack()
            if not all(w in hay for w in words):
                continue
            name = s.name.lower()
            if not words:
                tier = 0
            elif name.startswith(words[0]):
                tier = 3
            elif any(w in name for w in words):
                tier = 2
            elif any(w in s.short.lower() for w in words):
                tier = 1
            else:
                tier = 0
            out.append((-tier, -self.script_uses(s), s.order, s))
        return [t[-1] for t in sorted(out, key=lambda t: t[:3])]

    def ordered_commands(self, s):
        """Most used first, README order otherwise; the best match for the search on top."""
        words = self.search.get_text().lower().split()

        def key(item):
            i, (cmd, hint) = item
            text = f"{cmd} {hint}".lower()
            hits = sum(w in text for w in words if w not in s.name.lower())
            return (-hits, -self.cmd_uses(cmd), i)

        return [c for _, c in sorted(enumerate(s.commands), key=key)]

    # -- list building -------------------------------------------------------
    def refilter(self):
        for row in self.list.get_children():
            self.list.remove(row)
        self.visible = self.ranked(self.search.get_text())
        for s in self.visible:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            top = Gtk.Box(spacing=8)
            top.pack_start(label(s.name, ("name",)), False, False, 0)
            n = self.script_uses(s)
            if n:
                top.pack_end(label(f"×{n}", ("dim", "small")), False, False, 0)
            box.pack_start(top, False, False, 0)
            short = label(s.short, ("dim", "small"))
            short.set_ellipsize(3)  # Pango.EllipsizeMode.END
            box.pack_start(short, False, False, 0)
            row.add(box)
            row.script = s
            self.list.add(row)
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)
        else:
            self.show_script(None)

    def on_script_selected(self, _lb, row):
        self.show_script(row.script if row else None)

    def show_script(self, s):
        self.current = s
        for row in self.cmds.get_children():
            self.cmds.remove(row)
        self.cmd_rows = []
        if s is None:
            self.title.set_text("nothing found" if self.scripts else "no scripts")
            self.mode.set_text("")
            if self.scripts:
                self.desc.set_text("Nothing matches. Enter still runs the command below.")
            return
        self.title.set_text(s.name)
        self.mode.set_text("runs in a terminal" if s.terminal else "runs in the background")
        self.desc.set_markup("\n\n".join(md_markup(p) for p in s.paragraphs))
        for cmd, hint in self.ordered_commands(s):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12)
            c = label(cmd, ("name",))
            c.set_width_chars(24)
            c.set_ellipsize(3)
            box.pack_start(c, False, False, 0)
            box.pack_start(label(hint, ("dim",), wrap=True), True, True, 0)
            n = self.cmd_uses(cmd)
            if n:
                box.pack_end(label(f"×{n}", ("dim", "small")), False, False, 0)
            row.add(box)
            row.cmd = cmd
            self.cmds.add(row)
            self.cmd_rows.append(row)
        self.cmds.show_all()
        self.cmds.select_row(self.cmd_rows[0])

    def on_cmd_selected(self, _lb, row):
        if row is not None:
            self.cmdline.set_text(row.cmd)

    # -- keys ----------------------------------------------------------------
    def move(self, lb, delta):
        rows = lb.get_children()
        if not rows:
            return
        cur = lb.get_selected_row()
        i = rows.index(cur) if cur in rows else 0
        row = rows[max(0, min(len(rows) - 1, i + delta))]
        lb.select_row(row)
        adj = lb.get_parent().get_parent().get_vadjustment()  # viewport -> scrolledwindow
        ok, _x, y = row.translate_coordinates(lb, 0, 0)
        if ok:
            h = row.get_allocated_height()
            if y < adj.get_value():
                adj.set_value(y)
            elif y + h > adj.get_value() + adj.get_page_size():
                adj.set_value(y + h - adj.get_page_size())

    def on_key(self, _w, ev):
        k, st = ev.keyval, ev.state
        shift = bool(st & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(st & Gdk.ModifierType.CONTROL_MASK)
        if k == Gdk.KEY_Escape:
            self.quit()
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.run_current(shift)
        elif k == Gdk.KEY_Up:
            self.move(self.list, -1)
        elif k == Gdk.KEY_Down:
            self.move(self.list, 1)
        elif k in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            self.move(self.list, -5 if k == Gdk.KEY_Page_Up else 5)
        elif k == Gdk.KEY_Tab:
            self.move(self.cmds, 1)
        elif k == Gdk.KEY_ISO_Left_Tab:
            self.move(self.cmds, -1)
        elif ctrl and k in (Gdk.KEY_e, Gdk.KEY_E):
            self.cmdline.grab_focus()
            self.cmdline.set_position(-1)
        elif ctrl and k in (Gdk.KEY_f, Gdk.KEY_l):
            self.search.grab_focus()
        else:
            return False
        return True

    def on_focus_out(self, *_):
        # close like rofi when you click away (but not before we ever had focus)
        if self.had_focus:
            GLib.timeout_add(150, lambda: (self.is_active() or self.quit(), False)[1])
        return False

    # -- run -----------------------------------------------------------------
    def run_current(self, force_terminal):
        cmd = self.cmdline.get_text().strip()
        if not cmd:
            return
        s = self.current
        terminal = force_terminal or (s is not None and s.terminal)
        try:
            launch(cmd, self.names, terminal)
        except OSError as e:
            self.desc.set_markup(f'<span foreground="{C["alert"]}">'
                                 f"{html.escape(str(e))}</span>")
            return
        if s is not None:
            self.usage["scripts"][s.name] = self.script_uses(s) + 1
        self.usage["commands"][cmd] = self.cmd_uses(cmd) + 1
        save_usage(self.usage)
        self.quit()

    def quit(self, *_):
        try:
            if open(PIDFILE).read().split()[0] == str(os.getpid()):
                os.unlink(PIDFILE)
        except (OSError, IndexError):
            pass
        Gtk.main_quit()
        return True


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return
    # toggle: a second launch closes the open window
    try:
        pid = int(open(PIDFILE).read().split()[0])
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if SELF.encode() in f.read():  # not a stale pid that now belongs to something else
                os.kill(pid, signal.SIGTERM)
                return
    except (OSError, ValueError, IndexError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    GLib.set_prgname("script-launcher")
    Gdk.set_program_class("Script-launcher")  # WM_CLASS class, matched by the i3 rule
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-xft-antialias", 0)  # crisp pixel font, like the bar
    settings.set_property("gtk-xft-hinting", 0)
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_USER)
    win = Launcher()

    def got_focus(*_):
        win.had_focus = True
        return False

    win.connect("focus-in-event", got_focus)
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        sig_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        sig_add = GLib.unix_signal_add
    sig_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, win.quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
