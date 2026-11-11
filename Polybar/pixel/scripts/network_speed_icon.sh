#!/usr/bin/env bash
# Polybar network module: the icon shows how fast the link is.
#
#   network_speed_icon.sh   -> prints a status line every INTERVAL seconds (use with tail = true)
#
# Icon = link speed tier (Wi-Fi: negotiated bitrate, Ethernet: port speed)
#   Wi-Fi     󰤟 slow   󰤢 ok   󰤥 fast   󰤨 very fast
#   Ethernet  󰾆 slow   󰾅 ok   󰓅 fast
# The icon is also colored by tier.
# Click actions (Wi-Fi menu, toggle) are handled by network_final.sh.

export LC_NUMERIC=C

# ---------- Settings ----------
INTERVAL=2           # seconds between updates
MAX_LEN=20           # truncate long SSIDs
# Tier thresholds in Mbit/s: below T1 = slow, below T2 = ok, below T3 = fast, else very fast
T1=25 T2=100 T3=300

# colours of the current theme (written by ~/Desktop/dotfiles/Scripts/theme.py)
alert="#c96a5f" warn="#d8a657" accent="#8DB38B"
THEME_COLORS="$HOME/Desktop/dotfiles/themes/current/colors"
[[ -r $THEME_COLORS ]] && . "$THEME_COLORS"
COLOR_SLOW=$alert
COLOR_OK=$warn
COLOR_FAST=$accent
COLOR_OFF=$alert
COLOR_WARN=$warn

WIFI_ICONS=($'\U000f091f' $'\U000f0922' $'\U000f0925' $'\U000f0928') # 󰤟 󰤢 󰤥 󰤨
ETH_ICONS=($'\U000f0f86' $'\U000f0f85' $'\U000f04c5' $'\U000f04c5')  # 󰾆 󰾅 󰓅 󰓅
TIER_COLORS=("$COLOR_SLOW" "$COLOR_OK" "$COLOR_FAST" "$COLOR_FAST")
ICON_ETH=$'\U000f0200'     # 󰈀 (speed unknown)
ICON_NET=$'\U000f06f3'     # 󰛳 other link types
ICON_OFF=$'\U000f092e'     # 󰤮
ICON_WARN=$'\U000f0026'    # 󰀦

# ---------- Helpers ----------
tier_of() { # $1 = Mbit/s (integer)
    local m=${1:-0}
    if ((m < T1)); then echo 0
    elif ((m < T2)); then echo 1
    elif ((m < T3)); then echo 2
    else echo 3
    fi
}

truncate_str() {
    local s=$1
    ((${#s} > MAX_LEN)) && s="${s:0:MAX_LEN-1}…"
    printf '%s' "$s"
}

default_dev() {
    ip -o route show default 2>/dev/null |
        awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i+1); exit }}'
}

# ---------- Main loop ----------
print_status() {
    local dev icon color label="" mbit tier

    dev=$(default_dev)
    if [[ -z $dev || ! -d /sys/class/net/$dev ]]; then
        if [[ $(nmcli radio wifi 2>/dev/null) == disabled ]]; then
            echo "%{F$COLOR_OFF}$ICON_OFF Wi-Fi off%{F-}"
        else
            echo "%{F$COLOR_OFF}$ICON_OFF Disconnected%{F-}"
        fi
        return
    fi

    # --- link speed -> icon ---
    if [[ -d /sys/class/net/$dev/wireless ]]; then
        local link ssid
        link=$(iw dev "$dev" link 2>/dev/null)
        ssid=$(sed -n 's/^\s*SSID: //p' <<<"$link")
        mbit=$(awk '/rx bitrate:/ { printf "%d", $3; exit }' <<<"$link")
        [[ -n $mbit ]] || mbit=$(awk '/tx bitrate:/ { printf "%d", $3; exit }' <<<"$link")
        tier=$(tier_of "${mbit:-0}")
        icon=${WIFI_ICONS[tier]} color=${TIER_COLORS[tier]}
        label=$(truncate_str "${ssid:-$dev}")
    else
        mbit=$(cat "/sys/class/net/$dev/speed" 2>/dev/null)
        case $dev in
            e*)
                if [[ $mbit =~ ^[0-9]+$ ]] && ((mbit > 0)); then
                    tier=$(tier_of "$mbit")
                    icon=${ETH_ICONS[tier]} color=${TIER_COLORS[tier]}
                else
                    icon=$ICON_ETH color=$COLOR_FAST
                fi
                ;;
            *)
                icon=$ICON_NET color=$COLOR_FAST
                label=$dev
                ;;
        esac
    fi

    label=${label//%/%%} # polybar format escape
    local out="%{F$color}$icon%{F-}"
    [[ -n $label ]] && out+=" $label"

    case $(nmcli networking connectivity 2>/dev/null) in
        limited | portal | none) out+=" %{F$COLOR_WARN}$ICON_WARN%{F-}" ;;
    esac
    echo "$out"
}

trap 'exit 0' TERM INT
while true; do
    print_status
    sleep "$INTERVAL"
done
