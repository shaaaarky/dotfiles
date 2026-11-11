#!/usr/bin/env bash
#
# globalCursor.sh - cursor theme manager for Arch Linux (X11 / i3)
#
# Sets ONE cursor theme everywhere applications look for it:
#   GTK 2/3/4, the X "default" cursor theme (Xlib, Qt, Steam, Electron, ...),
#   X resources, XSettings daemons, GSettings, KDE, Flatpak, session environment.
# Existing settings in those files (GTK theme, fonts, icons, ...) are preserved.
#
# Usage:
#   globalCursor.sh            pick a theme interactively
#   globalCursor.sh --status   show where a cursor theme is configured (changes nothing)

set -eu

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

DEFAULT_SIZE=24
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_DIRS=("/usr/share/icons" "/usr/local/share/icons" "$HOME/.icons" "$XDG_DATA/icons")
MARK_BEGIN="# >>> globalCursor (managed) >>>"
MARK_END="# <<< globalCursor (managed) <<<"

have()    { command -v "$1" >/dev/null 2>&1; }
running() { pgrep -x "$1" >/dev/null 2>&1; }

usage() {
    echo "Usage: ${0##*/} [--status | --help]"
    echo "  (no args)   choose a cursor theme interactively and apply it everywhere"
    echo "  --status    show every place the cursor theme is configured, change nothing"
}

check_dependencies() {
    local deps=("find" "grep" "awk" "sed" "mktemp" "basename" "dirname" "sort")
    local missing=() dep

    for dep in "${deps[@]}"; do
        if ! have "$dep"; then
            missing+=("$dep")
        fi
    done

    if [ ${#missing[@]} -ne 0 ]; then
        echo -e "${RED}Error: Missing dependencies: ${missing[*]}${NC}"
        echo "Please install them using pacman"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# File helpers. All of them write THROUGH symlinks (cat >), so dotfiles managed
# with stow/yadm/etc. stay symlinks.
# ---------------------------------------------------------------------------

# ini_get FILE KEY -> value (quotes/whitespace stripped). Also fine for ~/.gtkrc-2.0.
ini_get() {
    [ -f "$1" ] || return 0
    awk -F= -v k="$2" '
        { key = $1; gsub(/^[ \t]+|[ \t]+$/, "", key) }
        key == k {
            v = substr($0, index($0, "=") + 1)
            gsub(/^[ \t"]+|[ \t"\r]+$/, "", v)
            print v
            exit
        }' "$1"
}

# ini_set FILE KEY VALUE -> set KEY inside [Settings], leave everything else alone
ini_set() {
    local file=$1 key=$2 value=$3 tmp
    mkdir -p "$(dirname "$file")"
    [ -f "$file" ] || : > "$file"
    tmp=$(mktemp)
    KEY=$key VAL=$value awk '
        BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"] }
        /^[ \t]*\[/ {
            if (insec && !done) { print k "=" v; done = 1 }
            insec = ($0 ~ /^[ \t]*\[Settings\][ \t]*$/)
            if (insec) seen = 1
        }
        insec && $0 ~ ("^[ \t]*" k "[ \t]*=") {
            if (!done) { print k "=" v; done = 1 }
            next
        }
        { print }
        END {
            if (!seen) { print "[Settings]"; print k "=" v }
            else if (!done) print k "=" v
        }' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# line_replace FILE REGEX LINE -> delete every line matching REGEX, then append LINE
line_replace() {
    local file=$1 pattern=$2 line=$3 tmp
    mkdir -p "$(dirname "$file")"
    [ -f "$file" ] || : > "$file"
    tmp=$(mktemp)
    grep -Ev "$pattern" "$file" > "$tmp" || true
    printf '%s\n' "$line" >> "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# write_block FILE CONTENT -> (re)write our marker-delimited block at the end of FILE
write_block() {
    local file=$1 content=$2 tmp
    [ -f "$file" ] || : > "$file"
    tmp=$(mktemp)
    awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
        $0 == b { skip = 1; next }
        $0 == e { skip = 0; next }
        !skip   { print }' "$file" > "$tmp"
    printf '%s\n%s\n%s\n' "$MARK_BEGIN" "$content" "$MARK_END" >> "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# Older versions of this script appended exports to ~/.bashrc / ~/.zshrc. Those
# stale lines override newer settings in every terminal-launched app, so drop them.
strip_legacy_exports() {
    local f tmp
    for f in "$HOME/.bashrc" "$HOME/.zshrc"; do
        if [ -f "$f" ] && grep -Eq '^[[:space:]]*export[[:space:]]+XCURSOR_(THEME|SIZE)=' "$f"; then
            tmp=$(mktemp)
            grep -Ev '^[[:space:]]*export[[:space:]]+XCURSOR_(THEME|SIZE)=' "$f" > "$tmp" || true
            cat "$tmp" > "$f"
            rm -f "$tmp"
            echo -e "  ${YELLOW}Removed old XCURSOR_* exports from $f${NC}"
        fi
    done
}

# ---------------------------------------------------------------------------
# Theme discovery
# ---------------------------------------------------------------------------

# Only directories that really contain cursors (not every icon theme), by directory
# name - that is the name GTK/Xcursor look up. "default" is excluded: selecting it
# would make ~/.icons/default inherit from itself.
find_cursor_themes() {
    local dir theme
    for dir in "${ICON_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            while IFS= read -r theme; do
                if [ -d "$theme/cursors" ]; then
                    basename "$theme"
                fi
            done < <(find -L "$dir" -mindepth 1 -maxdepth 1 -type d)
        fi
    done | grep -vx 'default' | sort -u
}

index_inherits() {
    local f="$HOME/.icons/default/index.theme"
    [ -f "$f" ] || return 0
    awk -F= '/^Inherits=/ { print $2; exit }' "$f"
}

current_theme() {
    local t
    t=$(ini_get "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-name)
    if [ -z "$t" ]; then
        t=$(index_inherits)
    fi
    printf '%s' "$t"
}

current_size() {
    local s
    s=$(ini_get "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-size)
    if [[ "$s" =~ ^[0-9]+$ ]] && [ "$s" -gt 0 ]; then
        printf '%s' "$s"
    else
        printf '%s' "$DEFAULT_SIZE"
    fi
}

display_themes() {
    local current=$1
    shift
    local i=1 theme

    echo -e "${BLUE}Available cursor themes:${NC}"
    echo "------------------------"
    for theme in "$@"; do
        if [ "$theme" = "$current" ]; then
            echo -e "${GREEN}[$i] $theme (current)${NC}"
        else
            echo -e "${YELLOW}[$i] $theme${NC}"
        fi
        i=$((i + 1))
    done
    echo "------------------------"
}

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

apply_cursor_theme() {
    local theme=$1 size=$2 d kw xs_conf

    echo -e "${GREEN}Applying cursor theme: $theme (size $size)${NC}"

    # 1. GTK 2 / 3 / 4  (edited in place - keeps your GTK theme, fonts, icons, ...)
    ini_set "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-name "$theme"
    ini_set "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-size "$size"
    ini_set "$HOME/.config/gtk-4.0/settings.ini" gtk-cursor-theme-name "$theme"
    ini_set "$HOME/.config/gtk-4.0/settings.ini" gtk-cursor-theme-size "$size"
    line_replace "$HOME/.gtkrc-2.0" '^[[:space:]]*gtk-cursor-theme-name[[:space:]]*=' "gtk-cursor-theme-name=\"$theme\""
    line_replace "$HOME/.gtkrc-2.0" '^[[:space:]]*gtk-cursor-theme-size[[:space:]]*=' "gtk-cursor-theme-size=$size"

    # 2. X "default" cursor theme: what Xlib/libXcursor, Qt, Steam, Electron, games
    #    use when nobody names a theme. (Old versions of this script made a
    #    "cursors" symlink here; remove it so index.theme is what counts.)
    for d in "$HOME/.icons/default" "$XDG_DATA/icons/default"; do
        mkdir -p "$d"
        if [ -L "$d/cursors" ]; then
            rm -f "$d/cursors"
        fi
        cat > "$d/index.theme" << EOF
[Icon Theme]
Name=Default
Comment=Default Cursor Theme
Inherits=$theme
EOF
    done

    # 3. X resources: file for next login + the running X server right now
    line_replace "$HOME/.Xresources" '^[[:space:]]*Xcursor[.*](theme|size)[[:space:]]*:' "Xcursor.theme: $theme"
    line_replace "$HOME/.Xresources" '^[[:space:]]*Xcursor[.*]size[[:space:]]*:' "Xcursor.size: $size"
    if have xrdb && [ -n "${DISPLAY:-}" ]; then
        printf 'Xcursor.theme: %s\nXcursor.size: %s\n' "$theme" "$size" | xrdb -merge || true
    fi

    # 4. XSettings managers (these OVERRIDE gtk settings.ini for running GTK apps)
    xs_conf="$HOME/.config/xsettingsd/xsettingsd.conf"
    if [ -f "$xs_conf" ]; then
        line_replace "$xs_conf" '^[[:space:]]*(Gtk|Net)/CursorTheme(Name|Size)[[:space:]]' "Gtk/CursorThemeName \"$theme\""
        line_replace "$xs_conf" '^[[:space:]]*Gtk/CursorThemeSize[[:space:]]' "Gtk/CursorThemeSize $size"
        if running xsettingsd; then
            pkill -HUP -x xsettingsd || true      # xsettingsd reloads its config on SIGHUP
        fi
    fi
    if running xfsettingsd && have xfconf-query; then
        xfconf-query -c xsettings -p /Gtk/CursorThemeName --create -t string -s "$theme" 2>/dev/null || true
        xfconf-query -c xsettings -p /Gtk/CursorThemeSize --create -t int -s "$size" 2>/dev/null || true
    fi

    # 5. GSettings / dconf (GNOME apps, portals, Wayland GTK, some Electron builds)
    if have gsettings; then
        timeout 5 gsettings set org.gnome.desktop.interface cursor-theme "$theme" 2>/dev/null || true
        timeout 5 gsettings set org.gnome.desktop.interface cursor-size "$size" 2>/dev/null || true
    fi

    # 6. KDE / Qt apps using the KDE platform theme
    for kw in kwriteconfig6 kwriteconfig5; do
        if have "$kw"; then
            "$kw" --file kcminputrc --group Mouse --key cursorTheme "$theme" || true
            "$kw" --file kcminputrc --group Mouse --key cursorSize "$size" || true
            break
        fi
    done

    # 7. Flatpak apps are sandboxed: give them the variables and read-only access
    #    to the icon directories so they can find the theme.
    if have flatpak; then
        flatpak override --user \
            --env=XCURSOR_THEME="$theme" --env=XCURSOR_SIZE="$size" \
            --filesystem="$HOME/.icons:ro" --filesystem=xdg-data/icons:ro 2>/dev/null || true
    fi

    # 8. Environment for future sessions. NOT ~/.bashrc: apps started from i3
    #    (dmenu/rofi/keybindings) never read it. ~/.xprofile is sourced by display
    #    managers (LightDM, SDDM, GDM, ...); with startx, ~/.xinitrc must source it.
    strip_legacy_exports
    write_block "$HOME/.xprofile" "export XCURSOR_THEME=$(printf '%q' "$theme")
export XCURSOR_SIZE=$size"

    # 9. Live session: D-Bus/systemd-activated apps, and the root window cursor
    #    (the one you see over empty desktop / empty i3 workspaces).
    if have dbus-update-activation-environment && [ -n "${DISPLAY:-}" ]; then
        dbus-update-activation-environment --systemd XCURSOR_THEME="$theme" XCURSOR_SIZE="$size" 2>/dev/null || true
    fi
    if have xsetroot && [ -n "${DISPLAY:-}" ]; then
        XCURSOR_THEME=$theme XCURSOR_SIZE=$size xsetroot -cursor_name left_ptr 2>/dev/null || true
    fi

    echo -e "${GREEN}Cursor theme applied!${NC}"
}

# ---------------------------------------------------------------------------
# Status / diagnostics
# ---------------------------------------------------------------------------

SEEN=()

row() {
    local label=$1 theme=${2:-} size=${3:-}
    if [ -z "$theme" ] && [ -z "$size" ]; then
        printf '  %-32s %s\n' "$label" "(not set)"
    else
        printf '  %-32s %s%s\n' "$label" "${theme:-?}" "${size:+  (size $size)}"
        if [ -n "$theme" ]; then
            SEEN+=("$theme")
        fi
    fi
}

xs_get() { # xsettingsd.conf KEY
    [ -f "$1" ] || return 0
    sed -n "s|^$2[[:space:]]*\"\{0,1\}\([^\"]*\)\"\{0,1\}[[:space:]]*\$|\1|p" "$1" | head -n 1
}

show_status() {
    local ff_pid ff_t ff_s xs_conf m f
    local mgrs=()

    echo -e "${BLUE}Where the cursor theme is configured:${NC}"
    SEEN=()

    row "GTK 3  (settings.ini)" "$(ini_get "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-name)" \
                                "$(ini_get "$HOME/.config/gtk-3.0/settings.ini" gtk-cursor-theme-size)"
    row "GTK 4  (settings.ini)" "$(ini_get "$HOME/.config/gtk-4.0/settings.ini" gtk-cursor-theme-name)" \
                                "$(ini_get "$HOME/.config/gtk-4.0/settings.ini" gtk-cursor-theme-size)"
    row "GTK 2  (~/.gtkrc-2.0)" "$(ini_get "$HOME/.gtkrc-2.0" gtk-cursor-theme-name)" \
                                "$(ini_get "$HOME/.gtkrc-2.0" gtk-cursor-theme-size)"
    row "X default (~/.icons/default)" "$(index_inherits)"

    if have xrdb && [ -n "${DISPLAY:-}" ]; then
        row "X resources (running server)" \
            "$(xrdb -query 2>/dev/null | sed -n 's/^Xcursor[.*]theme:[[:space:]]*//p' | head -n 1)" \
            "$(xrdb -query 2>/dev/null | sed -n 's/^Xcursor[.*]size:[[:space:]]*//p' | head -n 1)"
    fi

    row "Environment of this shell" "${XCURSOR_THEME:-}" "${XCURSOR_SIZE:-}"

    ff_pid=$(pgrep -xo firefox 2>/dev/null || true)
    if [ -n "$ff_pid" ] && [ -r "/proc/$ff_pid/environ" ]; then
        ff_t=$(tr '\0' '\n' < "/proc/$ff_pid/environ" | sed -n 's/^XCURSOR_THEME=//p' | head -n 1)
        ff_s=$(tr '\0' '\n' < "/proc/$ff_pid/environ" | sed -n 's/^XCURSOR_SIZE=//p' | head -n 1)
        row "Running Firefox (pid $ff_pid) env" "$ff_t" "$ff_s"
    fi

    for m in xsettingsd xfsettingsd gsd-xsettings lxsession; do
        if running "$m"; then
            mgrs+=("$m")
        fi
    done
    if [ ${#mgrs[@]} -gt 0 ]; then
        echo -e "  ${YELLOW}XSettings manager running: ${mgrs[*]}${NC} (overrides settings.ini in running GTK apps)"
    fi
    xs_conf="$HOME/.config/xsettingsd/xsettingsd.conf"
    if [ -f "$xs_conf" ]; then
        row "xsettingsd.conf" "$(xs_get "$xs_conf" 'Gtk\/CursorThemeName')" "$(xs_get "$xs_conf" 'Gtk\/CursorThemeSize')"
    fi
    if have gsettings; then
        m=$(timeout 5 gsettings get org.gnome.desktop.interface cursor-theme 2>/dev/null | tr -d "'" || true)
        echo "  $(printf '%-32s' 'GSettings (informational)') ${m:-(not available)}"
    fi

    echo ""
    local hits=0
    for f in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.zprofile" \
             "$HOME/.xprofile" "$HOME/.xinitrc" "$HOME/.pam_environment" /etc/environment \
             "$HOME"/.config/environment.d/*.conf; do
        if [ -f "$f" ] && grep -Eq 'XCURSOR_(THEME|SIZE)' "$f"; then
            if [ "$hits" -eq 0 ]; then
                echo -e "${BLUE}Files that set XCURSOR_* (these win over everything else for new apps):${NC}"
            fi
            hits=$((hits + 1))
            grep -HnE 'XCURSOR_(THEME|SIZE)' "$f" | sed 's/^/  /'
        fi
    done
    if [ "$hits" -gt 0 ]; then
        echo ""
    fi

    if [ ${#SEEN[@]} -gt 0 ] && [ "$(printf '%s\n' "${SEEN[@]}" | sort -u | wc -l)" -gt 1 ]; then
        echo -e "${RED}Mismatch: these sources name different themes. Apps that read the stale one show${NC}"
        echo -e "${RED}the wrong cursor. Already-running apps need a restart (or re-login for the${NC}"
        echo -e "${RED}environment); a stale file value is fixed by re-running this script.${NC}"
    elif [ ${#SEEN[@]} -gt 0 ]; then
        echo -e "${GREEN}All detected sources agree on: ${SEEN[0]}${NC}"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    case "${1:-}" in
        -s|--status) show_status; exit 0 ;;
        -h|--help)   usage; exit 0 ;;
        "")          ;;
        *)           echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac

    check_dependencies

    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║      Arch Linux Cursor Manager       ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
    echo ""

    if [ -z "${DISPLAY:-}" ]; then
        echo -e "${YELLOW}No X display detected: config files will be written, live reload steps skipped.${NC}"
        echo ""
    fi

    local themes=()
    mapfile -t themes < <(find_cursor_themes)

    if [ ${#themes[@]} -eq 0 ]; then
        echo -e "${RED}No cursor themes found!${NC}"
        echo "Please install some cursor themes first, e.g.:"
        echo "  sudo pacman -S xcursor-premium xcursor-vanilla-dmz"
        echo "  or from the AUR: yay -S bibata-cursor-theme"
        exit 1
    fi

    display_themes "$(current_theme)" "${themes[@]}"

    local selection size default_size
    echo -ne "${BLUE}Select cursor theme (1-${#themes[@]}): ${NC}"
    read -r selection || selection=""

    if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt ${#themes[@]} ]; then
        echo -e "${RED}Invalid selection!${NC}"
        exit 1
    fi

    default_size=$(current_size)
    echo -ne "${BLUE}Cursor size [${default_size}]: ${NC}"
    read -r size || size=""
    size=${size:-$default_size}
    if ! [[ "$size" =~ ^[0-9]+$ ]] || [ "$size" -lt 8 ] || [ "$size" -gt 256 ]; then
        echo -e "${RED}Invalid size (use 8-256)!${NC}"
        exit 1
    fi

    echo ""
    apply_cursor_theme "${themes[$((selection - 1))]}" "$size"

    echo ""
    show_status

    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo -e "${YELLOW}  - Restart Firefox and other open apps: they read the cursor theme only at startup.${NC}"
    echo -e "${YELLOW}  - Log out and back in once so everything launched from i3 inherits the new XCURSOR_* values.${NC}"
    if [ -f "$HOME/.xinitrc" ] && ! grep -q 'xprofile' "$HOME/.xinitrc"; then
        echo -e "${YELLOW}  - You use ~/.xinitrc: add  [ -f ~/.xprofile ] && . ~/.xprofile  near the top, before exec i3.${NC}"
    fi
    echo ""
    echo -e "${GREEN}Done!${NC}"
}

main "$@"
