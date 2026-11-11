#!/usr/bin/env bash
# Polybar network module (NetworkManager + rofi)
#
#   network.sh watch    -> prints the status line, re-prints on every network event (use with tail = true)
#   network.sh menu     -> Wi-Fi picker; selecting a network connects to it
#   network.sh toggle   -> turn Wi-Fi on/off
#
# Requires: NetworkManager (nmcli), rofi (or dmenu), a Nerd Font.
# Optional: libnotify (notify-send), nm-connection-editor.

# ---------- Settings ----------
MAX_LEN=22                 # truncate long SSIDs/connection names in the bar
COLOR_OFF="#f7768e"        # disconnected
COLOR_WARN="#e0af68"       # connected but no internet

ICON_ETH=$'\U000f0200'     # 󰈀
ICON_WIFI=$'\U000f05a9'    # 󰖩
ICON_OFF=$'\U000f05aa'     # 󰖪
ICON_NET=$'\U000f06f3'     # 󰛳  (other connection types)
ICON_LOCK=$'\U000f033e'    # 󰌾
ICON_REFRESH=$'\U000f0450' # 󰑐
ICON_COG=$'\U000f0493'     # 󰒓
ICON_WARN=$'\U000f0026'    # 󰀦
SIGNAL_ICONS=($'\U000f091f' $'\U000f0922' $'\U000f0925' $'\U000f0928')

ACT_RESCAN="$ICON_REFRESH  Rescan"
ACT_OFF="$ICON_OFF  Turn Wi-Fi off"
ACT_DISC="$ICON_OFF  Disconnect"
ACT_EDIT="$ICON_COG  Advanced settings"

# ---------- Helpers ----------
notify() {
    command -v notify-send >/dev/null 2>&1 && notify-send -a "Network" "$@"
}

signal_icon() { # $1 = 0-100
    local s=${1:-0} i=0
    ((s >= 25)) && i=1
    ((s >= 50)) && i=2
    ((s >= 75)) && i=3
    printf '%s' "${SIGNAL_ICONS[i]}"
}

truncate_str() {
    local s=$1
    ((${#s} > MAX_LEN)) && s="${s:0:MAX_LEN-1}…"
    printf '%s' "$s"
}

unescape() { # nmcli -t escapes ':' and '\'
    local s=$1
    s=${s//\\:/:}
    s=${s//\\\\/\\}
    printf '%s' "$s"
}

wifi_dev() {
    nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}'
}

launcher() { # $1 = prompt, items on stdin
    if command -v rofi >/dev/null 2>&1; then
        rofi -dmenu -i -no-custom -p "$1"
    elif command -v dmenu >/dev/null 2>&1; then
        dmenu -i -l 15 -p "$1"
    else
        notify "Network menu" "Install rofi or dmenu"
        return 1
    fi
}

ask_password() { # $1 = ssid
    if command -v rofi >/dev/null 2>&1; then
        rofi -dmenu -password -p "Password for $1" </dev/null
    else
        dmenu -p "Password for $1 (visible!)" </dev/null
    fi
}

# ---------- Status ----------
print_status() {
    local default_dev d t s c dev="" type="" conn=""

    default_dev=$(ip -o route show default 2>/dev/null |
        awk '{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}')

    # Pick the device that carries the default route, otherwise the first connected one
    while IFS=: read -r d t s c; do
        [[ $s == connected* ]] || continue
        case $t in ethernet | wifi | gsm | cdma | bluetooth) ;; *) continue ;; esac
        if [[ -z $dev || $d == "$default_dev" ]]; then
            dev=$d type=$t conn=$(unescape "$c")
        fi
    done < <(nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null)

    if [[ -z $dev ]]; then
        if [[ $(nmcli radio wifi 2>/dev/null) == disabled ]]; then
            echo "%{F$COLOR_OFF}$ICON_OFF Wi-Fi off%{F-}"
        else
            echo "%{F$COLOR_OFF}$ICON_OFF Disconnected%{F-}"
        fi
        returnk
    fi

    local icon label
    case $type in
        ethernet)
            icon=$ICON_ETH
            label="Ethernet"
            ;;
        wifi)
            local signal ssid
            IFS=: read -r signal ssid < <(
                nmcli -t -f IN-USE,SIGNAL,SSID device wifi list ifname "$dev" --rescan no 2>/dev/null |
                    sed -n 's/^\*://p'
            )
            ssid=$(unescape "${ssid:-$conn}")
            icon=$(signal_icon "$signal")
            label="WiFi | $ssid"
            ;;
        *)
            icon=$ICON_NET
            label="$type | $conn"
            ;;
    esac

    label=$(truncate_str "$label")
    label=${label//%/%%} # polybar format escape

    local out="$icon $label"
    case $(nmcli networking connectivity 2>/dev/null) in
        limited | portal) out+=" %{F$COLOR_WARN}$ICON_WARN%{F-}" ;;
    esac
    echo "$out"
}

watch() {
    local fd pid rc
    exec {fd}< <(nmcli monitor 2>/dev/null)
    pid=$!
    trap 'kill "$pid" 2>/dev/null' EXIT
    trap 'exit 0' TERM INT

    print_status
    while true; do
        read -r -t 10 -u "$fd" _
        rc=$?
        if ((rc == 0)); then
            # swallow the burst of events NM emits on a change
            while read -r -t 0.5 -u "$fd" _; do :; done
        elif ((rc <= 128)); then
            break # nmcli monitor died (NetworkManager restarted?)
        fi
        print_status
    done
    exec {fd}<&-
}

# ---------- Wi-Fi menu ----------
ACTIVE_SSID=""
NET_LINES=()
declare -gA NET_SSID=() NET_SEC=()

load_networks() {
    NET_LINES=()
    NET_SSID=()
    NET_SEC=()
    ACTIVE_SSID=""

    local inuse signal sec ssid line mark lock
    local -A seen=()

    # Strongest AP first so duplicates (mesh/extenders) collapse to the best one
    while IFS=: read -r inuse signal sec ssid; do
        ssid=$(unescape "$ssid")
        [[ -n $ssid && -z ${seen["$ssid"]-} ]] || continue
        seen["$ssid"]=1
        [[ $sec == -- ]] && sec=""

        mark="  "
        lock=""
        [[ -n $sec ]] && lock=" $ICON_LOCK"

        # in-use flag may belong to a weaker duplicate, so compare by SSID below
        line="$(signal_icon "$signal")  $ssid$lock"
        NET_LINES+=("$line")
        NET_SSID["$line"]=$ssid
        NET_SEC["$line"]=$sec
    done < <(nmcli -t -f IN-USE,SIGNAL,SECURITY,SSID device wifi list --rescan no 2>/dev/null |
        sort -t: -k2,2nr)

    ACTIVE_SSID=$(nmcli -t -f IN-USE,SSID device wifi list --rescan no 2>/dev/null |
        sed -n 's/^\*://p' | head -n1)
    ACTIVE_SSID=$(unescape "$ACTIVE_SSID")

    # Mark the active network
    local i
    for i in "${!NET_LINES[@]}"; do
        line=${NET_LINES[i]}
        if [[ ${NET_SSID["$line"]} == "$ACTIVE_SSID" && -n $ACTIVE_SSID ]]; then
            local new="● ${line}"
            NET_SSID["$new"]=${NET_SSID["$line"]}
            NET_SEC["$new"]=${NET_SEC["$line"]}
            NET_LINES[i]=$new
        fi
    done
}

saved_uuid() { # $1 = ssid -> UUID of a saved Wi-Fi profile with that name
    local esc=${1//:/\\:} l rest
    while IFS= read -r l; do
        if [[ $l == "$esc:802-11-wireless:"* ]]; then
            rest=${l#"$esc:802-11-wireless:"}
            printf '%s' "$rest"
            return 0
        fi
    done < <(nmcli -t -f NAME,TYPE,UUID connection show 2>/dev/null)
    return 1
}

connect_wifi() { # $1 = ssid, $2 = security string
    local ssid=$1 sec=$2 uuid pass out had_profile=0

    notify "Connecting to $ssid…"

    if uuid=$(saved_uuid "$ssid"); then
        had_profile=1
        if out=$(nmcli --wait 25 connection up uuid "$uuid" 2>&1); then
            notify "Connected to $ssid"
            return 0
        fi
        # Saved profile failed (changed password, out of range, ...). Fall through
        # and ask for a password again if the network is secured.
        [[ -z $sec ]] && {
            notify -u critical "Failed to connect to $ssid" "$out"
            return 1
        }
    fi

    if [[ -z $sec ]]; then
        # Open network
        if out=$(nmcli --wait 25 device wifi connect "$ssid" 2>&1); then
            notify "Connected to $ssid"
        else
            nmcli connection delete id "$ssid" >/dev/null 2>&1
            notify -u critical "Failed to connect to $ssid" "$out"
            return 1
        fi
        return 0
    fi

    if [[ $sec == *802.1X* ]]; then
        notify "$ssid uses enterprise (802.1X) security" "Configure it in Advanced settings first."
        command -v nm-connection-editor >/dev/null 2>&1 && nm-connection-editor &
        return 1
    fi

    pass=$(ask_password "$ssid") || return 1
    [[ -n $pass ]] || return 1

    if ((had_profile)); then
        nmcli connection modify uuid "$uuid" wifi-sec.psk "$pass" >/dev/null 2>&1
        out=$(nmcli --wait 25 connection up uuid "$uuid" 2>&1)
    else
        out=$(nmcli --wait 25 device wifi connect "$ssid" password "$pass" 2>&1)
    fi

    if (($? == 0)); then
        notify "Connected to $ssid"
        return 0
    fi

    # Don't leave a broken profile behind if we just created it
    ((had_profile)) || nmcli connection delete id "$ssid" >/dev/null 2>&1
    notify -u critical "Failed to connect to $ssid" "Wrong password?"
    return 1
}

menu() {
    exec 9>"${XDG_RUNTIME_DIR:-/tmp}/polybar-network-menu.lock"
    flock -n 9 || exit 0 # one menu at a time

    if [[ -z $(wifi_dev) ]]; then
        notify "No Wi-Fi adapter found"
        exit 0
    fi

    local choice ssid entries
    while true; do
        if [[ $(nmcli radio wifi) != enabled ]]; then
            choice=$(printf '%s\n' "$ICON_WIFI  Enable Wi-Fi" | launcher "Wi-Fi") || return
            [[ -n $choice ]] || return
            nmcli radio wifi on
            sleep 2
            continue
        fi

        load_networks

        entries=("${NET_LINES[@]}" "$ACT_RESCAN" "$ACT_OFF")
        [[ -n $ACTIVE_SSID ]] && entries+=("$ACT_DISC")
        entries+=("$ACT_EDIT")

        choice=$(printf '%s\n' "${entries[@]}" | launcher "Wi-Fi") || return

        case $choice in
            "") return ;;
            "$ACT_RESCAN")
                nmcli device wifi rescan >/dev/null 2>&1
                sleep 3
                continue
                ;;
            "$ACT_OFF")
                nmcli radio wifi off
                return
                ;;
            "$ACT_DISC")
                nmcli device disconnect "$(wifi_dev)" >/dev/null 2>&1
                return
                ;;
            "$ACT_EDIT")
                if command -v nm-connection-editor >/dev/null 2>&1; then
                    nm-connection-editor &
                else
                    notify "nm-connection-editor is not installed"
                fi
                return
                ;;
        esac

        ssid=${NET_SSID["$choice"]-}
        [[ -n $ssid ]] || return

        if [[ $ssid == "$ACTIVE_SSID" ]]; then
            notify "Already connected to $ssid"
            return
        fi

        connect_wifi "$ssid" "${NET_SEC["$choice"]}"
        return
    done
}

toggle() {
    if [[ $(nmcli radio wifi) == enabled ]]; then
        nmcli radio wifi off
    else
        nmcli radio wifi on
    fi
}

case ${1:-watch} in
    watch) watch ;;
    status) print_status ;;
    menu) menu ;;
    toggle) toggle ;;
    *)
        echo "usage: ${0##*/} [watch|status|menu|toggle]" >&2
        exit 1
        ;;
esac
