#!/usr/bin/env bash

# Terminate already running polybar instances
killall -q polybar

# Wait until the processes have been shut down
while pgrep -x polybar >/dev/null; do sleep 1; done

# Launch polybar on each connected monitor
#if type "xrandr" >/dev/null 2>&1; then
#    for m in $(xrandr --query | grep " connected" | cut -d" " -f1); do
#        MONITOR=$m polybar --reload minimalist -c ~/Desktop/dotfiles/Polybar/minimal/config.ini &
#    done
#else
#    polybar --reload minimalist -c ~/Desktop/dotfiles/Polybar/minimal/config.ini &
#fi
# Launching just one polybar 
polybar --reload minimalist -c ~/Desktop/dotfiles/Polybar/minimal/config.ini &

echo "Polybar launched"
