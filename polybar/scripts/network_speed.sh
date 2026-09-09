#!/usr/bin/env bash
# ~/.config/polybar/scripts/network_speed.sh
# Detects the active default-route interface and reports its
# upload/download speed, sampled over a fixed interval.
 
INTERVAL=1
GREEN="#a6e3a1"
BLUE="#89b4fa"
RED="#f38ba8"
 
iface=$(ip route show default | awk '/default/ {print $5; exit}')
 
if [[ -z "$iface" ]]; then
    printf '%%{F%s} Disconnected%%{F-}\n' "$RED"
    exit 0
fi
 
rx_path="/sys/class/net/${iface}/statistics/rx_bytes"
tx_path="/sys/class/net/${iface}/statistics/tx_bytes"
 
if [[ ! -r "$rx_path" || ! -r "$tx_path" ]]; then
    echo "$iface (no stats)"
    exit 0
fi
 
rx1=$(<"$rx_path")
tx1=$(<"$tx_path")
sleep "$INTERVAL"
rx2=$(<"$rx_path")
tx2=$(<"$tx_path")
 
rx_rate=$(( (rx2 - rx1) / INTERVAL ))
tx_rate=$(( (tx2 - tx1) / INTERVAL ))
 
# Convert bytes/sec to a human-readable string (B, KB, MB)
human() {
    local bytes=$1
    if (( bytes >= 1048576 )); then
        printf "%.1fMB/s" "$(echo "$bytes / 1048576" | bc -l)"
    elif (( bytes >= 1024 )); then
        printf "%.1fKB/s" "$(echo "$bytes / 1024" | bc -l)"
    else
        printf "%dB/s" "$bytes"
    fi
}
 
down=$(human "$rx_rate")
up=$(human "$tx_rate")
 
case "$iface" in
    e*)
        color="$GREEN"
        label=""
        ;;
    w*)
        color="$BLUE"
        label=""
        ;;
    *)
        color="$BLUE"
        label="$iface"
        ;;
esac
 
printf '%%{F%s} %s%%{F-}  DOWN %s UP %s\n' "$color" "$label" "$down" "$up"
