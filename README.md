# dotfiles
## Easy install 
Run `./install.sh` to symlink `i3/` and `Polybar/` into `~/.config` (as `~/.config/i3` and `~/.config/polybar`).
Each bar has its own `config.ini` and a `scripts/` folder for its modules. 

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

### cursor.sh
<!-- launcher: terminal -->
I was annoyed when the default lxappearance menu didnt correctly switch my cursor for all apps so this script neatly does it for all of them. It sets the same one for GTK 2/3/4, X resources, Qt, XSettings, GSettings, KDE and Flatpak.

```sh
cursor.sh            # pick a theme and size interactively
cursor.sh --status   # show where a cursor theme is currently set, change nothing
```

### unify_displays.sh
Mirrors every connected monitor onto the first one, using a resolution they share (it falls back to `--auto` if there isn't one). With a single monitor it just turns it on as primary. Takes no arguments.
