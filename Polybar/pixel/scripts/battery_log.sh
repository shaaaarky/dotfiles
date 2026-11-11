#!/usr/bin/env bash
# Records the battery % once a minute for the history graph in the power popup
# (pixelpop.py power). i3 starts it at login; only one copy runs at a time.
#
# Log: ${XDG_STATE_HOME:-~/.local/state}/battery_history, one "EPOCH PERCENT STATUS"
# line per minute. Entries older than 48h are dropped once an hour (~100KB max).

LOG="${XDG_STATE_HOME:-$HOME/.local/state}/battery_history"
KEEP_SECONDS=$((48 * 3600))
EVERY=60

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/battery_log.lock"
flock -n 9 || exit 0

bat=$(compgen -G '/sys/class/power_supply/BAT*' | sort | head -n1)
[[ -n $bat ]] || exit 0   # no battery (desktop): nothing to log
mkdir -p "$(dirname "$LOG")"

n=0
while true; do
    if cap=$(<"$bat/capacity") 2>/dev/null; then
        status=$(<"$bat/status") 2>/dev/null
        printf '%s %s %s\n' "$(date +%s)" "$cap" "${status:-Unknown}" >>"$LOG"
    fi
    if ((n++ % 60 == 0)); then
        cutoff=$(($(date +%s) - KEEP_SECONDS))
        awk -v c="$cutoff" '$1 >= c' "$LOG" >"$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"
    fi
    sleep "$EVERY"
done
