#!/usr/bin/env bash

mapfile -t outputs < <(xrandr --query | grep " connected" | cut -d" " -f1)

# Extract the list of modes for a given output name
get_modes() {
    xrandr --query | awk -v out="$1" '
        $0 ~ "^"out" " {flag=1; next}
        /^[A-Za-z0-9_-]+ (connected|disconnected)/ {flag=0}
        flag {print $1}
    '
}

if [ "${#outputs[@]}" -eq 1 ]; then
    xrandr --output "${outputs[0]}" --auto --primary
elif [ "${#outputs[@]}" -ge 2 ]; then
    primary="${outputs[0]}"
    mapfile -t primary_modes < <(get_modes "$primary")

    xrandr --output "$primary" --auto --primary

    for output in "${outputs[@]:1}"; do
        common_mode=""
        while IFS= read -r m; do
            for pm in "${primary_modes[@]}"; do
                if [ "$m" == "$pm" ]; then
                    common_mode="$m"
                    break 2
                fi
            done
        done < <(get_modes "$output")

        if [ -n "$common_mode" ]; then
            xrandr --output "$output" --mode "$common_mode" --same-as "$primary"
        else
            echo "Warning: no shared resolution between $primary and $output, falling back to --auto" >&2
            xrandr --output "$output" --auto --same-as "$primary"
        fi
    done
fi
