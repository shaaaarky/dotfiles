#!/usr/bin/env bash
# Polybar brightness slider for ALL connected displays (xrandr, software brightness).
#
#   brightness_slider.sh watch      -> prints the slider (use with tail = true)
#   brightness_slider.sh set <PCT>  -> set brightness (clamped to MIN..MAX)
#   brightness_slider.sh up|down    -> change by SCROLL_STEP
#   brightness_slider.sh get        -> print current percentage
#
# Click a segment of the slider to jump to that value, scroll for fine steps.
# Values are clamped so the screen can never go black (MIN) or washed out (MAX).

export LC_NUMERIC=C

# ---------- Settings ----------
MIN=10          # percent: hard floor, nothing can set brightness below this
MAX=100         # percent: highest allowed (>100 washes out colors)
SCROLL_STEP=5   # percent per scroll tick
SEGMENTS=10     # slider segments; each one is MAX/SEGMENTS percent

COLOR_FILL="#8DB38B"
COLOR_KNOB="#8DB38B"
COLOR_EMPTY="#8DB38B"

FILL="━"
KNOB="●"
EMPTY="─"
ICON_LOW=$'\xf3\xb0\x83\x9e'   # 󰃞 (raw UTF-8 bytes: works in any locale)
ICON_MED=$'\xf3\xb0\x83\x9f'   # 󰃟
ICON_HIGH=$'\xf3\xb0\x83\xa0'  # 󰃠

SELF=$(readlink -f "$0")
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_FILE="$STATE_DIR/brightness_slider"
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}"
PID_PREFIX="$RUN_DIR/brightness_slider.pid"

# ---------- Helpers ----------
clamp() { # $1 = integer percent
    local p=$1
    ((p < MIN)) && p=$MIN
    ((p > MAX)) && p=$MAX
    echo "$p"
}

connected_outputs() {
    xrandr --query | awk '/ connected/ {print $1}'
}

# Read the real brightness of the first connected display (used when no saved state)
read_from_xrandr() {
    local o
    o=$(connected_outputs | head -n1)
    [[ -n $o ]] || return 1
    xrandr --verbose | awk -v o="$o" '
        $1 == o            { f = 1; next }
        f && /^[^ \t]/     { f = 0 }
        f && /Brightness:/ { printf "%d", $2 * 100 + 0.5; exit }'
}

read_pct() {
    local p=""
    [[ -r $STATE_FILE ]] && p=$(<"$STATE_FILE")
    [[ $p =~ ^[0-9]+$ ]] || p=$(read_from_xrandr)
    [[ $p =~ ^[0-9]+$ ]] || p=$MAX
    clamp "$p"
}

apply_pct() { # $1 = already-clamped integer percent
    local val args=() o p
    p=$(clamp "$1")
    val=$(awk -v p="$p" 'BEGIN { printf "%.2f", p / 100 }')
    while read -r o; do
        [[ -n $o ]] && args+=(--output "$o" --brightness "$val")
    done < <(connected_outputs)
    ((${#args[@]})) && xrandr "${args[@]}"
}

# Tell every running slider instance (one per bar) to redraw
poke_watchers() {
    local f pid
    for f in "$PID_PREFIX".*; do
        [[ -e $f ]] || continue
        pid=${f##*.}
        kill -USR1 "$pid" 2>/dev/null || rm -f "$f"
    done
}

set_pct() {
    local p=$1
    [[ $p =~ ^[0-9]+$ ]] || {
        echo "usage: ${0##*/} set <PERCENT>" >&2
        exit 1
    }
    p=$(clamp "$p")
    mkdir -p "$STATE_DIR"
    echo "$p" >"$STATE_FILE"
    apply_pct "$p"
    poke_watchers
}

# ---------- Rendering ----------
render() {
    local pct knob i v glyph color out="" icon
    pct=$(read_pct)

    # Segment 1 = MIN, last segment = MAX
    knob=$((((pct - MIN) * (SEGMENTS - 1) * 2 + (MAX - MIN)) / (2 * (MAX - MIN)) + 1))
    ((knob < 1)) && knob=1
    ((knob > SEGMENTS)) && knob=$SEGMENTS

    if ((pct < 40)); then
        icon=$ICON_LOW
    elif ((pct < 75)); then
        icon=$ICON_MED
    else
        icon=$ICON_HIGH
    fi

    for ((i = 1; i <= SEGMENTS; i++)); do
        v=$((MIN + ((i - 1) * (MAX - MIN) + (SEGMENTS - 1) / 2) / (SEGMENTS - 1)))
        if ((i < knob)); then
            glyph=$FILL color=$COLOR_FILL
        elif ((i == knob)); then
            glyph=$KNOB color=$COLOR_KNOB
        else
            glyph=$EMPTY color=$COLOR_EMPTY
        fi
        out+="%{A1:$SELF set $v:}%{F$color}$glyph%{F-}%{A}"
    done

    printf '%s %s\n' "$icon" "$out"
}

watch() {
    local pidfile="$PID_PREFIX.$$" spid
    echo $$ >"$pidfile"
    trap 'rm -f "$pidfile"' EXIT
    trap 'exit 0' TERM INT
    trap : USR1

    # Re-apply the saved value on startup (xrandr resets after reboot/replug)
    [[ -r $STATE_FILE ]] && apply_pct "$(read_pct)"

    while true; do
        render
        sleep 30 &
        spid=$!
        wait "$spid"
        kill "$spid" 2>/dev/null
    done
}

case ${1:-watch} in
    watch) watch ;;
    set) set_pct "${2:-}" ;;
    up) set_pct $(($(read_pct) + SCROLL_STEP)) ;;
    down) set_pct $(($(read_pct) - SCROLL_STEP)) ;;
    get) read_pct ;;
    *)
        echo "usage: ${0##*/} [watch|set <PCT>|up|down|get]" >&2
        exit 1
        ;;
esac