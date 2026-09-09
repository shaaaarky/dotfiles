#!/usr/bin/env bash
# ~/.config/polybar/scripts/network_status.sh

iface=$(ip route show default | awk '/default/ {print $5; exit}')

GREEN="#a6e3a1"
BLUE="#89b4fa"
RED="#f38ba8"
LIGHT_BLUE="#9dbfcc"

if [[ -z "$iface" ]]; then
    printf '%%{F%s} Disconnected%%{F-}\n' "$RED"
    exit 0
fi

case "$iface" in
    e*)
        printf '%%{F%s} 󰈀 Wired%%{F-} %s\n' "$LIGHT_BLUE" "$iface"
        ;;
    w*)
        ssid=$(iwgetid -r 2>/dev/null)
        printf '%%{F%s} 󰖩 WiFi%%{F-}: %s\n' "$BLUE" "${ssid:-$iface}"
        ;;
    *)
        echo "$iface"
        ;;
esac
