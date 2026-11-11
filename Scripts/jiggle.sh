#!/usr/bin/env bash
# Nudge the mouse just before the idle timeout so the screen never blanks or locks.
#
# Usage: mouse-jiggle.sh [IDLE_SECONDS]     (default: 540 = 9 minutes)
# Requires: xdotool, xprintidle   (sudo pacman -S xdotool xprintidle)
#
# How it works: every few seconds it asks X how long you've been idle. Once that
# reaches IDLE_SECONDS it moves the pointer 1px and puts it back, which resets
# X's idle timer. Real activity resets the timer too, so it only acts when idle.

THRESHOLD=${1:-540}
CHECK_EVERY=15   # seconds between idle checks

if ! [[ $THRESHOLD =~ ^[0-9]+$ ]] || ((THRESHOLD < 1)); then
    echo "usage: ${0##*/} [IDLE_SECONDS]" >&2
    exit 1
fi

for cmd in xdotool xprintidle; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "${0##*/}: '$cmd' not found (sudo pacman -S $cmd)" >&2
        exit 1
    }
done

# Only one instance at a time
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/mouse-jiggle.lock"
flock -n 9 || {
    echo "${0##*/}: already running" >&2
    exit 1
}

jiggle() {
    local x y
    read -r x y < <(xdotool getmouselocation | sed -E 's/x:([0-9]+) y:([0-9]+).*/\1 \2/')
    [[ $x =~ ^[0-9]+$ && $y =~ ^[0-9]+$ ]] || return 1

    xdotool mousemove_relative -- 1 1
    sleep 0.05
    xdotool mousemove "$x" "$y" # absolute restore: no drift, even at a screen edge
}

while true; do
    if idle_ms=$(xprintidle 2>/dev/null) && [[ $idle_ms =~ ^[0-9]+$ ]]; then
        if (( idle_ms / 1000 >= THRESHOLD )); then
            jiggle
        fi
    fi
    sleep "$CHECK_EVERY"
done
