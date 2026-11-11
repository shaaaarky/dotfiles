#!/usr/bin/env bash

# Universal GPU monitor - works with NVIDIA, AMD, Intel (integrated & dedicated)

get_nvidia() {
    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null 2>&1; then
        nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv,noheader,nounits | \
        awk '{printf "GPU %d%% %d°C", $1, $2}'
        return 0
    fi
    return 1
}

get_amd() {
    # Try radeontop for AMD
    if command -v radeontop &> /dev/null; then
        local usage=$(radeontop -d - -l 1 2>/dev/null | grep -oP 'gpu\s+\K[0-9.]+' | head -1)
        if [[ -n "$usage" ]]; then
            usage=${usage%.*}
            local temp=$(sensors 2>/dev/null | grep -i "amdgpu\|edge" | grep -oP '\d+\.\d+' | head -1)
            if [[ -n "$temp" ]]; then
                temp=${temp%.*}
                echo "GPU ${usage}% ${temp}°C"
            else
                echo "GPU ${usage}%"
            fi
            return 0
        fi
    fi
    
    # Try sysfs for AMD
    for card in /sys/class/drm/card*; do
        if [[ -f "$card/device/gpu_busy_percent" ]]; then
            local usage=$(cat "$card/device/gpu_busy_percent" 2>/dev/null)
            if [[ -n "$usage" ]]; then
                local temp=""
                local temp_file=$(find "$card/device/hwmon" -name "temp1_input" 2>/dev/null | head -1)
                if [[ -n "$temp_file" ]]; then
                    temp=$(cat "$temp_file" 2>/dev/null)
                    temp=$((temp / 1000))
                    echo "GPU ${usage}% ${temp}°C"
                else
                    echo "GPU ${usage}%"
                fi
                return 0
            fi
        fi
    done
    return 1
}

get_intel() {
    # Try intel_gpu_top for Intel
    if command -v intel_gpu_top &> /dev/null; then
        local usage=$(intel_gpu_top -J -l 1 2>/dev/null | grep -oP '"render":\s*\K[0-9.]+' | head -1)
        if [[ -n "$usage" ]]; then
            usage=${usage%.*}
            local temp=$(sensors 2>/dev/null | grep -E "Core [0-9]+" | grep -oP '\+\K[0-9.]+' | head -1)
            if [[ -n "$temp" ]]; then
                temp=${temp%.*}
                echo "GPU ${usage}% ${temp}°C"
            else
                echo "GPU ${usage}%"
            fi
            return 0
        fi
    fi
    
    # Try sysfs for Intel (frequency-based usage)
    for card in /sys/class/drm/card*; do
        for freq_file in "$card/gt_cur_freq_mhz" "$card/device/gt_cur_freq_mhz"; do
            if [[ -f "$freq_file" ]]; then
                local freq=$(cat "$freq_file" 2>/dev/null | head -1)
                if [[ -n "$freq" && "$freq" -gt 0 ]]; then
                    local max_file="${freq_file%_freq_mhz}_max_freq_mhz"
                    if [[ -f "$max_file" ]]; then
                        local max=$(cat "$max_file" 2>/dev/null)
                        if [[ -n "$max" && "$max" -gt 0 ]]; then
                            local usage=$((freq * 100 / max))
                            echo "GPU ${usage}%"
                            return 0
                        fi
                    fi
                fi
            fi
        done
    done
    return 1
}

get_fallback() {
    # Just show temperature if available
    if command -v sensors &> /dev/null; then
        local temp=$(sensors 2>/dev/null | grep -E "edge|temp1|Core" | grep -oP '\+\K[0-9.]+' | head -1)
        if [[ -n "$temp" ]]; then
            temp=${temp%.*}
            echo "GPU ${temp}°C"
            return 0
        fi
    fi
    return 1
}

# Try each GPU type in order
if get_nvidia; then
    exit 0
elif get_amd; then
    exit 0
elif get_intel; then
    exit 0
elif get_fallback; then
    exit 0
else
    echo "GPU N/A"
    exit 1
fi
