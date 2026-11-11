#!/usr/bin/env bash

# Power menu with rofi

# Define menu options
options="󰐥 Shutdown\n󰜉 Reboot\n󰤄 Suspend\n󰍃 Logout"

# Show menu and get selection
choice=$(echo -e "$options" | rofi -dmenu -p "Power Menu" -i -theme-str 'window {width: 20%;} listview {lines: 5;}')

case "$choice" in
    *"Suspend") systemctl suspend ;;
    *"Reboot") systemctl reboot ;;
    *"Shutdown") systemctl poweroff ;;
    *"Logout") i3-msg exit ;;
    *"Lock") i3lock -c 000000 ;;
esac
