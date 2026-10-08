# UPLINK-9

A retro green-phosphor terminal OS for handheld Linux devices. It boots
straight into a glowing green terminal, records holotapes, reads and writes
USB drives, fires webhooks and updates itself from this GitHub repo.

It runs by **touch alone** (no keyboard needed) and detects a touchscreen
automatically. A physical keyboard works too, whenever one is attached.

```
 UPLINK-9 // BOOT

 UPLINK-9 TERMINAL  v0.2.0
 4RDEN SYSTEMS // FIELD UNIT

 MEMORY CHECK ......... 3790 MB
 USB BUS .............. 1 DRIVE(S)
 NETWORK .............. 192.168.1.42
 UPDATE CHANNEL ....... TAGS
 CHECKING UPDATES ..... UP TO DATE

 READY.
```

## Features

| Section | What it does |
|---|---|
| **Holotapes** | Text logs, plus audio recordings when `arecord` is installed. Playback types the log out like a tape. |
| **Messages** | Compose messages, keep a log on the device, optionally relay them through a webhook (e.g. a Discord channel). |
| **USB drives** | Detects and mounts sticks, browses files, views text files, copies files both ways, exports/imports holotapes, ejects safely. |
| **Webhooks** | Add Discord, ntfy or generic JSON webhooks and send pings or messages. |
| **System** | Check/install updates from GitHub, plain mode toggle, device info (battery, network, disk), exit to shell, reboot, shut down. |

## Touch and screens

UPLINK-9 draws straight to the device's display (no desktop needed) and picks
its controls by itself:

- **Touchscreen found** → touch mode: big tap targets, swipe to scroll, a
  **BACK** button in the title bar, and an on-screen keyboard for typing.
  If detection ever misses one, the first tap switches touch mode on.
- **No touchscreen** → compact layout driven by the keyboard.
- **Over SSH** (or no graphics available) → the same app in text mode.

Detection reads the kernel's input device list and looks for devices that
report absolute positions and are marked as sitting on a display, which
excludes touchpads. Check what it finds with `uplink --detect`.

Force a choice with `--gui` / `--tty` and `--touch` / `--no-touch`, or the
`interface` and `touch` settings in the config.

**Plain mode** (accessibility): no colour, no typing animation, no flicker,
no boot sequence. Turn it on in SYSTEM, or start once with `uplink --plain`.

## Keys (optional)

With a keyboard attached, everything works without arrow keys too:

| Key | Action |
|---|---|
| `j` / `k` (or `s` / `w`, arrows) | move down / up |
| `ENTER` or `space` | select |
| `1`-`9` | jump straight to a menu entry |
| `q`, `ESC` or `backspace` | back |
| any key during an animation | skip it |
| `Ctrl+U` in a text field | clear it |

## Install on the device

Needs Linux with Python 3.9+, git and pygame (`python3-pygame`) for the
graphical/touch screen. Without pygame it still runs in text mode.

```sh
git clone https://github.com/FELIXJZN/uplink-9.git
cd uplink-9
./scripts/install.sh --deps --autostart --autologin
sudo reboot
```

- `--deps` installs `python3-pygame`, fonts, `git`, `alsa-utils` (audio holotapes) and `udisks2` (USB mounting) with apt, and adds you to the `video`, `input` and `audio` groups so the screen and touchscreen work without root.
- `--autostart` launches UPLINK-9 whenever you log in on the first console (tty1).
- `--autologin` logs in on tty1 at boot, so the device boots straight into the terminal.
- Plain `./scripts/install.sh` just installs the `uplink` command and a config.

Exit UPLINK-9 (`q` on the main menu, or SYSTEM > EXIT TO SHELL) to get a normal
shell. `./scripts/uninstall.sh` removes the launcher, autostart and autologin.

## Updates

The device pulls updates from this repo. Two channels, set in the config:

- **`tags`** (default, recommended): only installs releases you tag. A half-finished push to `main` can never break the device.
- **`branch`**: follows the newest commit on `main`.

To ship a release from your PC:

```sh
git tag v0.2.0
git push --tags
```

The device checks on boot (when online) and shows `SYSTEM (UPDATE READY)`.
Install it from SYSTEM > INSTALL UPDATE and the terminal restarts on the new
version. From a shell: `python3 -m uplink.updater --apply`.

The updater never downgrades, and it refuses to update if files were edited
directly on the device.

## Config

`~/.config/uplink/config.json` (created from `config.example.json`). Data
(holotapes, messages, copied files) lives in `~/.local/share/uplink`.

```json
{
  "callsign": "UPLINK-9",
  "interface": "auto",
  "touch": "auto",
  "gui": { "fullscreen": "auto", "window": [800, 480], "font_size": 0 },
  "plain_mode": false,
  "effects": { "boot_sequence": true, "typing": true, "typing_delay_ms": 8, "flicker": true, "scanlines": true },
  "update": { "remote": "origin", "channel": "tags", "branch": "main", "check_on_boot": true },
  "webhooks": [
    { "name": "discord", "url": "https://discord.com/api/webhooks/...", "format": "discord" }
  ],
  "messages": { "relay_webhook": "discord" }
}
```

Webhook formats: `discord`, `ntfy` (plain text body), `json` (generic:
`source`, `event`, `text`, `timestamp`). Webhook URLs are secrets, so
the config file is in `.gitignore`; never commit it.

## Development

```sh
python3 -m uplink            # run it (opens a window on a desktop)
python3 -m uplink --no-boot  # skip the boot sequence
python3 -m uplink --touch    # try the touch layout with your mouse
python3 -m unittest discover tests
```

On Windows: `pip install pygame`, then `python -m uplink` opens it in a
window, mouse clicks act as taps. Text mode needs WSL or `windows-curses`.
Code layout:

```
uplink/
  __main__.py   entry point, restart handling
  app.py        boot sequence, main menu
  gui.py        graphical + touch screen (pygame)
  ui.py         text-mode screen (curses), same methods as gui.py
  touch.py      touchscreen detection
  holotapes.py  messages.py  usb.py  webhooks.py  system.py
  updater.py    GitHub update channels
  config.py     config + data paths
scripts/        install.sh, uninstall.sh
tests/          unit tests (simulated taps, fake remote repo for updates)
```

## Roadmap

- Receiving messages (needs a small server or a relay the device can poll)
- Incoming webhooks / remote commands
- Holotape playback with waveform display
- Companion iPhone / Apple Watch apps

## License

GPL-3.0. See [LICENSE](LICENSE). You can use, change and share UPLINK-9, but
anything you distribute that's built from it must stay open source under the
same license.
