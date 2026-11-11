#!/usr/bin/env bash
# cyberdeck-optimize.sh
# System optimization for sharky@cyberdeck (ThinkPad T480, Debian Trixie)
# Covers: systemd-oomd, zram, CPU governor, I/O scheduler
# Behavior: performance on AC, balanced/powersave on battery
#
# Usage:
#   sudo ./cyberdeck-optimize.sh          # apply everything (one-time or re-run)
#   sudo ./cyberdeck-optimize.sh --status # show current state of all settings

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
err()     { echo -e "${RED}[ERR ]${RESET}  $*" >&2; }
section() { echo -e "\n${BOLD}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }

# ─── Root check ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Run as root: sudo $0"
    exit 1
fi

# ─── Status mode ──────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--status" ]]; then
    section "System Status"

    echo -e "\n${BOLD}Power source:${RESET}"
    if cat /sys/class/power_supply/AC/online 2>/dev/null | grep -q 1; then
        echo "  AC adapter connected"
    else
        echo "  Battery (discharging)"
    fi

    echo -e "\n${BOLD}CPU governor:${RESET}"
    for cpu in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
        echo "  $(basename $(dirname $(dirname $cpu))): $(cat $cpu)"
    done | sort -u

    echo -e "\n${BOLD}I/O scheduler:${RESET}"
    for dev in /sys/block/sd* /sys/block/nvme* 2>/dev/null; do
        [[ -e "$dev/queue/scheduler" ]] && echo "  $(basename $dev): $(cat $dev/queue/scheduler)"
    done

    echo -e "\n${BOLD}Zram:${RESET}"
    if lsmod | grep -q zram; then
        swapon --show | grep zram || echo "  zram module loaded but no swap active"
    else
        echo "  zram not loaded"
    fi

    echo -e "\n${BOLD}systemd-oomd:${RESET}"
    systemctl is-active systemd-oomd && systemctl status systemd-oomd --no-pager -l | tail -5 || true

    echo -e "\n${BOLD}Memory accounting:${RESET}"
    grep -r "DefaultMemoryAccounting" /etc/systemd/system.conf.d/ 2>/dev/null || echo "  No override found (using default)"

    exit 0
fi

# ─── Detect power source ──────────────────────────────────────────────────────
ON_AC=false
if cat /sys/class/power_supply/AC/online 2>/dev/null | grep -q 1; then
    ON_AC=true
fi

if $ON_AC; then
    info "Power source: AC adapter → using performance profile"
else
    info "Power source: Battery → using balanced/powersave profile"
fi

# ══════════════════════════════════════════════════════════════════════════════
section "1. systemd-oomd"
# ══════════════════════════════════════════════════════════════════════════════

# Enable memory accounting globally (required for oomd to monitor units)
mkdir -p /etc/systemd/system.conf.d/
cat > /etc/systemd/system.conf.d/memory-accounting.conf <<EOF
[Manager]
DefaultMemoryAccounting=yes
EOF
ok "DefaultMemoryAccounting=yes set"

# oomd config: tune thresholds
mkdir -p /etc/systemd/
cat > /etc/systemd/oomd.conf <<EOF
[OOM]
# Kill a cgroup when swap usage exceeds this system-wide
SwapUsedLimit=80%
# Kill a cgroup when its memory pressure exceeds this for the duration below
DefaultMemoryPressureLimit=60%
DefaultMemoryPressureDurationSec=20s
EOF
ok "oomd.conf written (swap limit 80%, pressure limit 60%)"

# Enable and start
systemctl daemon-reload
systemctl enable --now systemd-oomd
ok "systemd-oomd enabled and started"

# ══════════════════════════════════════════════════════════════════════════════
section "2. Zram"
# ══════════════════════════════════════════════════════════════════════════════

# Install zram-tools if not present
if ! dpkg -s zram-tools &>/dev/null; then
    info "Installing zram-tools..."
    apt-get install -y zram-tools
fi

# Configure: use 25% of RAM (~4GB on this 15.5GB machine), lz4 for speed
cat > /etc/default/zramswap <<EOF
# zramswap configuration for cyberdeck (15.51 GiB RAM)
ALGO=lz4
PERCENT=25
PRIORITY=100
EOF
ok "zramswap configured: lz4, 25% RAM (~3.9 GiB compressed swap)"

# Restart service to apply
systemctl restart zramswap || systemctl enable --now zramswap
ok "zramswap service active"

# ══════════════════════════════════════════════════════════════════════════════
section "3. CPU Governor (hybrid AC/battery)"
# ══════════════════════════════════════════════════════════════════════════════

# Install cpupower if not present
if ! command -v cpupower &>/dev/null; then
    info "Installing linux-cpupower..."
    apt-get install -y linux-cpupower
fi

# Install TLP for automatic AC/battery switching
if ! dpkg -s tlp &>/dev/null; then
    info "Installing TLP (automatic power management)..."
    apt-get install -y tlp tlp-rdw
fi

# TLP config for ThinkPad T480 — AC performance, battery balanced
cat > /etc/tlp.d/50-cyberdeck.conf <<EOF
# TLP config for ThinkPad T480 (cyberdeck)
# AC: performance, Battery: powersave with schedutil

# CPU scaling governor
CPU_SCALING_GOVERNOR_ON_AC=performance
CPU_SCALING_GOVERNOR_ON_BAT=schedutil

# CPU energy/performance policy (EPP) — requires intel_pstate
CPU_ENERGY_PERF_POLICY_ON_AC=performance
CPU_ENERGY_PERF_POLICY_ON_BAT=balance_power

# Turbo boost: always on AC, off on battery to save power
CPU_BOOST_ON_AC=1
CPU_BOOST_ON_BAT=0

# ThinkPad battery charge thresholds (extend battery lifespan)
# Start charging at 20%, stop at 80%
START_CHARGE_THRESH_BAT0=20
STOP_CHARGE_THRESH_BAT0=80

# Platform profile
PLATFORM_PROFILE_ON_AC=performance
PLATFORM_PROFILE_ON_BAT=balanced
EOF
ok "TLP configured: performance on AC, schedutil on battery"

systemctl enable --now tlp
ok "TLP service enabled and started"

# Apply governor right now based on current power state
if $ON_AC; then
    cpupower frequency-set -g performance &>/dev/null && ok "CPU governor set to: performance (AC)"
else
    cpupower frequency-set -g schedutil &>/dev/null && ok "CPU governor set to: schedutil (battery)"
fi

# ══════════════════════════════════════════════════════════════════════════════
section "4. I/O Scheduler"
# ══════════════════════════════════════════════════════════════════════════════

# Detect disk type and set appropriate scheduler via udev rules
# BFQ for HDDs (better latency), mq-deadline for SSDs/NVMe
cat > /etc/udev/rules.d/60-io-scheduler.rules <<'EOF'
# I/O scheduler tuning for cyberdeck
# SSD / NVMe → mq-deadline (low latency, good for SSDs)
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
# HDD → bfq (fair queuing, better interactivity under load)
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"
EOF
ok "udev rules written for I/O scheduler"

# Apply immediately to all current block devices
for dev in /sys/block/sd* /sys/block/nvme*; do
    [[ ! -e "$dev/queue/scheduler" ]] && continue
    devname=$(basename "$dev")
    rotational=$(cat "$dev/queue/rotational" 2>/dev/null || echo 0)
    if [[ "$devname" == nvme* ]] || [[ "$rotational" == "0" ]]; then
        echo "mq-deadline" > "$dev/queue/scheduler" 2>/dev/null && ok "$devname → mq-deadline"
    else
        echo "bfq" > "$dev/queue/scheduler" 2>/dev/null && ok "$devname → bfq"
    fi
done

udevadm control --reload-rules
ok "udev rules reloaded"

# ══════════════════════════════════════════════════════════════════════════════
section "5. Install power-switching hook (udev on AC plug/unplug)"
# ══════════════════════════════════════════════════════════════════════════════

# When AC is plugged/unplugged, re-apply CPU governor immediately
# (TLP handles this, but this is an explicit fallback)
cat > /usr/local/bin/cyberdeck-power-switch <<'EOF'
#!/usr/bin/env bash
# Called by udev when AC state changes
if cat /sys/class/power_supply/AC/online | grep -q 1; then
    cpupower frequency-set -g performance
else
    cpupower frequency-set -g schedutil
fi
EOF
chmod +x /usr/local/bin/cyberdeck-power-switch

cat > /etc/udev/rules.d/61-power-switch.rules <<'EOF'
SUBSYSTEM=="power_supply", ATTR{online}=="*", RUN+="/usr/local/bin/cyberdeck-power-switch"
EOF
udevadm control --reload-rules
ok "AC plug/unplug hook installed"

# ══════════════════════════════════════════════════════════════════════════════
section "Done"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${GREEN}${BOLD}All optimizations applied.${RESET}"
echo ""
echo -e "  ${BOLD}Reboot recommended${RESET} for memory accounting changes to take full effect."
echo ""
echo -e "  Check status anytime with:  ${CYAN}sudo $0 --status${RESET}"
echo -e "  Check oomd targets with:    ${CYAN}sudo oomctl${RESET}"
echo -e "  Check TLP status with:      ${CYAN}sudo tlp-stat -s${RESET}"
echo ""
