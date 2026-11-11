#!/usr/bin/env bash
set -euo pipefail

# Physical path (pwd -P), so links point at the real repo even if it's reached through a symlink
DOTFILES_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG_HOME="${XDG_CONFIG_HOME:-"$HOME/.config"}"
BACKUP_SUFFIX="backup.$(date +%Y%m%d%H%M%S)"

# i3/config, the bar configs and the scripts all refer to the repo by this path
EXPECTED_DIR="$HOME/Desktop/dotfiles"

# "source in dotfiles:name in ~/.config" (just "name" when they're the same)
configs=(
  "i3"
  "Polybar:polybar"
)

# Commands the configs and scripts call (warned about, not installed)
commands=(
  i3 polybar picom rofi feh python3 xfce4-terminal xfconf-query
  xdotool xprintidle brightnessctl scrot notify-send nmcli pactl xrandr setxkbmap
)

log() {
  printf '%s\n' "$*"
}

warn() {
  printf 'Warning: %s\n' "$*" >&2
}

# Move $1 out of the way. mv -T so an existing backup (or a symlink to a
# directory) is never treated as a folder to move into; a counter keeps two
# backups made in the same second apart.
backup() {
  local path="$1"
  local dest="$path.$BACKUP_SUFFIX"
  local n=1

  while [[ -e "$dest" || -L "$dest" ]]; do
    dest="$path.$BACKUP_SUFFIX.$n"
    n=$((n + 1))
  done

  log "Backing up: $path -> $dest"
  mv -T -- "$path" "$dest"
}

link() {
  local source_path="$1"
  local target_path="$2"

  if [[ ! -e "$source_path" ]]; then
    warn "skipping $target_path: $source_path does not exist"
    return
  fi

  if [[ -L "$target_path" ]]; then
    # Compare resolved paths, so a link made through another path to the repo still counts
    if [[ "$(readlink -f -- "$target_path")" == "$source_path" ]]; then
      log "Already linked: $target_path -> $source_path"
      return
    fi
    backup "$target_path"
  elif [[ -e "$target_path" ]]; then
    backup "$target_path"
  fi

  mkdir -p -- "$(dirname -- "$target_path")"
  ln -sn -- "$source_path" "$target_path"
  log "Linked: $target_path -> $source_path"
}

link_config() {
  local source_name="${1%%:*}"
  local name="${1#*:}"
  link "$DOTFILES_DIR/$source_name" "$CONFIG_HOME/$name"
}

# If the repo was cloned somewhere else, link it to the path the configs expect
link_repo() {
  if [[ "$(readlink -f -- "$EXPECTED_DIR" 2>/dev/null)" == "$DOTFILES_DIR" ]]; then
    return
  fi

  if [[ -e "$EXPECTED_DIR" || -L "$EXPECTED_DIR" ]]; then
    warn "$EXPECTED_DIR exists and isn't this repo ($DOTFILES_DIR)."
    warn "i3/config and the bar configs use $EXPECTED_DIR, so they won't find these files."
    return
  fi

  link "$DOTFILES_DIR" "$EXPECTED_DIR"
}

check_commands() {
  local missing=()
  local cmd

  for cmd in "${commands[@]}"; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done

  if ((${#missing[@]})); then
    warn "not installed: ${missing[*]}"
  fi

  if command -v python3 >/dev/null 2>&1 &&
    ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    warn "python GTK bindings are missing (pacman -S python-gobject gtk3); the bar popups and script launcher need them"
  fi

  if command -v fc-list >/dev/null 2>&1 && ! fc-list -q Terminus; then
    warn "Terminus font not found (pacman -S terminus-font); i3 and the pixel bar use it"
  fi
}

link_repo

mkdir -p -- "$CONFIG_HOME"

for config in "${configs[@]}"; do
  link_config "$config"
done

check_commands

log "Done."
