# dotfiles

i3 + polybar rice for Arch (ThinkPad T480). Run `./install.sh` to symlink `i3/` and `Polybar/` into `~/.config` (as `~/.config/i3` and `~/.config/polybar`).

| Folder | What's in it |
| --- | --- |
| `i3/` | i3 config |
| `Polybar/full/` | the original bar: every module, including brightness and temperature |
| `Polybar/minimal/` | a trimmed-down version of the full bar |
| `Polybar/pixel/` | pixel-art bar with pop-out menus (`pixelpop.py`) and an Alt+Tab switcher, the one in daily use |
| `themes/` | colour themes (`*.theme`) and the generated `current/` folder |
| `picom/` | compositor config |
| `Scripts/` | standalone scripts, described below |

Each bar has its own `config.ini` and a `scripts/` folder for its modules. Use `choose_polybar.sh` to switch between them. The pixel bar also has `battery_log.sh`, which i3 starts at login. It records the battery % once a minute (keeping 48h, in `~/.local/state/battery_history`) for the graph in the battery popup.

## Scripts

All of these live in `Scripts/`. The quickest way to run them is the launcher (Mod4+x). It builds its list from this section, so anything added here shows up there too.

### script_launcher.py
A searchable launcher for every script below. Bound to Mod4+x.

- Type to search names, descriptions and commands. The scripts you use most are listed first.
- Up/Down picks a script, Tab picks one of its commands, and Enter runs it. Shift+Enter runs it in a terminal instead.
- Ctrl+E lets you edit the command (add arguments) before running it.

To add a script, give it a `### name` heading here with a short explanation and a `sh` code block of commands. Comments written as `  # ...` become the hints shown next to each command. Put `<!-- launcher: terminal -->` under the heading if the script should open in a terminal (because it asks questions, needs sudo, or prints output you want to read). Everything else runs in the background, and any output shows up as a notification.

### theme.py
Switches the colour theme of xfce4-terminal, rofi, i3, every polybar and the wallpaper in one go.

```sh
theme.py              # pick a theme from a rofi menu (also bound to Mod4+t)
theme.py moss         # apply themes/moss.theme
theme.py list         # list themes (* = current)
theme.py reapply      # re-apply the current theme after editing its file
theme.py check        # validate the theme files without applying anything
theme.py wallpaper    # set the current wallpaper (i3 runs this at login)
```

To make a new theme, copy `themes/moss.theme` and edit the colours. Don't edit `themes/current/`, since it's regenerated on every switch.

### choose_polybar.sh
Lists every `Polybar/*/config.ini` in a rofi menu (zenity if rofi isn't installed) and restarts polybar with the one you pick. It remembers your choice.

```sh
choose_polybar.sh          # show the menu
choose_polybar.sh --last   # relaunch the last chosen bar without a menu (i3 runs this)
```

If a bar doesn't show up, the errors are in `$XDG_RUNTIME_DIR/polybar.log`.

### jiggle.sh
Stops the screen from blanking or locking. When you've been idle for close to the timeout, it moves the mouse 1px and back. Only one copy runs at a time, and i3 starts it on login.

```sh
jiggle.sh        # nudge after 540s (9 min) idle
jiggle.sh 240    # custom idle threshold in seconds
```

Needs `xdotool` and `xprintidle`.

### cursor.sh
<!-- launcher: terminal -->
Sets one cursor theme for everything: GTK 2/3/4, X resources, Qt, XSettings, GSettings, KDE and Flatpak. Your other settings in those files are kept.

```sh
cursor.sh            # pick a theme and size interactively
cursor.sh --status   # show where a cursor theme is currently set, change nothing
```

### unify_displays.sh
Mirrors every connected monitor onto the first one, using a resolution they share (it falls back to `--auto` if there isn't one). With a single monitor it just turns it on as primary. Takes no arguments.

### remote_build.sh
<!-- launcher: terminal -->
Copies a source file to a Windows VM over SSH, compiles it with MinGW gcc, runs it and prints the output back here.

```sh
remote_build.sh ./hello.c -o hello   # build + run hello.c on the VM (edit the file name first)
```

Set `REMOTE_USER`, `REMOTE_HOST`, `REMOTE_DIR` and `SSH_KEY` at the top of the script first. The VM needs OpenSSH Server, and gcc has to be on its PATH.

### optimization.sh
<!-- launcher: terminal -->
**Unfinished.** System tuning for the T480: systemd-oomd, zram, TLP (performance on AC, powersave on battery, 20–80% charge thresholds) and I/O schedulers. It was written for Debian, so check it before running it on Arch.

```sh
sudo optimization.sh            # apply everything
sudo optimization.sh --status   # show the current state
```

The long-term idea is to grow this into something that works on any WM, DE or distro.
