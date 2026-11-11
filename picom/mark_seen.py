#!/usr/bin/env python3
"""mark_seen.py: lets picom tell brand-new windows apart from windows i3 shows again.

i3 hides windows when you switch workspaces or go fullscreen, and picom treats
their reappearance as "opening", so the open ripple (picom.conf + ripple.glsl)
would play on every workspace switch. This helper listens to i3 and, shortly after
a window really opens, sets an X property _PIXEL_SEEN=1 on it. The ripple rule in
picom.conf only matches windows without that property, so it plays once per window.

i3 starts it (exec_always); only one copy runs. Windows that already exist when it
starts are marked straight away.
"""
import fcntl
import json
import os
import subprocess
import sys
import threading

PROP = "_PIXEL_SEEN"
DELAY = 0.6  # seconds: longer than the ripple (0.3s), so it isn't cut short
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mark_seen.lock")


def mark(wid):
    subprocess.run(["xprop", "-id", str(wid), "-f", PROP, "32c", "-set", PROP, "1"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def client_windows(node):
    if node.get("window"):
        yield node["window"]
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from client_windows(child)


def main():
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # already running

    events = subprocess.Popen(["i3-msg", "-t", "subscribe", "-m", '["window"]'],
                              stdout=subprocess.PIPE, text=True)
    tree = subprocess.run(["i3-msg", "-t", "get_tree"], capture_output=True, text=True).stdout
    try:
        for wid in client_windows(json.loads(tree)):
            mark(wid)
    except ValueError:
        pass

    for line in events.stdout:  # ends when i3 exits or restarts (i3 starts us again)
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("change") == "new" and ev.get("container", {}).get("window"):
            threading.Timer(DELAY, mark, [ev["container"]["window"]]).start()


if __name__ == "__main__":
    sys.exit(main())
