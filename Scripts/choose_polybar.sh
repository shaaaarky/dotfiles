#!/usr/bin/env bash
# Pick which polybar config to run from a GUI menu (rofi, falls back to zenity).
#
# Lists every ~/Desktop/dotfiles/Polybar/*/config.ini, marks the one that is
# currently running, then restarts polybar with the one you choose.
# The choice is remembered.
#
#   choose_polybar.sh          -> show the menu
#   choose_polybar.sh --last   -> no menu, launch the last chosen config
#                                 (use this in i3 instead of launch_polybars.sh)

DOTFILES="$HOME/Desktop/dotfiles"
DEFAULT_CONFIG="$DOTFILES/Polybar/full/config.ini"
STATE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/polybar_choice"
LOG_FILE="${XDG_RUNTIME_DIR:-/tmp}/polybar.log"

bar_name() { # $1 = config path -> name of the first [bar/NAME] section
    sed -n 's/^\[bar\/\([^]]*\)\].*/\1/p' "$1" | head -n1
}

launch() { # $1 = config path
    local bar
    bar=$(bar_name "$1")
    bar=${bar:-main}
    killall -q polybar
    while pgrep -x polybar >/dev/null; do sleep 0.2; done
    # setsid: fully detach so closing the terminal/rofi can't take the bar down.
    # Errors go to $LOG_FILE (check it if the bar doesn't show up).
    setsid -f polybar --reload "$bar" -c "$1" >"$LOG_FILE" 2>&1 </dev/null
}

if [[ ${1-} == --last ]]; then
    config=""
    [[ -r $STATE_FILE ]] && config=$(<"$STATE_FILE")
    [[ -f $config ]] || config=$DEFAULT_CONFIG
    launch "$config"
    exit 0
fi

# ---------- Find configs ----------
configs=()
for f in "$DOTFILES"/Polybar/*/config.ini; do
    [[ -f $f ]] && configs+=("$(realpath "$f")")
done

if ((${#configs[@]} == 0)); then
    notify-send -a Polybar "No polybar configs found in $DOTFILES" 2>/dev/null
    exit 1
fi

# Config of the running bar (if any), resolved so symlinks compare equal
running=""
if pid=$(pgrep -xo polybar); then
    cfg=$(tr '\0' '\n' </proc/"$pid"/cmdline | awk 'p { print; exit } $0 == "-c" || $0 == "--config" { p = 1 }')
    [[ -n $cfg ]] && running=$(realpath "${cfg/#\~/$HOME}" 2>/dev/null)
fi

# ---------- Build menu ----------
entries=()
declare -A path_of=()
for c in "${configs[@]}"; do
    name=$(basename "$(dirname "$c")")
    label=$name
    [[ $c == "$running" ]] && label="$name  (running)"
    entries+=("$label")
    path_of["$label"]=$c
done

# ---------- Ask ----------
if command -v rofi >/dev/null 2>&1; then
    choice=$(printf '%s\n' "${entries[@]}" | rofi -dmenu -i -no-custom -p "Polybar config") || exit 0
elif command -v zenity >/dev/null 2>&1; then
    choice=$(zenity --list --title="Polybar" --text="Which polybar config?" \
        --column="Config" "${entries[@]}" --height=300) || exit 0
else
    echo "Install rofi or zenity" >&2
    exit 1
fi

config=${path_of["$choice"]-}
[[ -n $config ]] || exit 0

# ---------- Remember + relaunch ----------
mkdir -p "$(dirname "$STATE_FILE")"
printf '%s\n' "$config" >"$STATE_FILE"
launch "$config"

notify-send -a Polybar "Polybar: $(basename "$(dirname "$config")")" 2>/dev/null
exit 0
