# Uplink-9

A 4RDEN Industries terminal for a handheld Linux computer (HackberryPi CM5, uConsole, or any Raspberry Pi).
It boots straight into a green-phosphor terminal: no desktop, no browser. It works by **touch alone**
on a touchscreen, by keyboard, or both.

- **Files:** browse, view, copy, move, rename, delete, new folders and notes
- **USB drives:** plug one in and it shows up, mounts, and can be ejected safely
- **Transfer:** Taildrop, rsync or croc
- **Messages:** threads that post to a webhook; ntfy threads are two-way
- **Nodes:** ping your machines, Wake-on-LAN, open an SSH shell
- **VPN:** switch between Tailscale, Twingate or off (one at a time)
- **Holotape:** record from the microphone, play back, export to USB and import from USB
- **Settings:** display color, screen and touch, accessibility, webhooks, firmware updates from GitHub
- **Phone link:** the Uplink-9 iPhone and Apple Watch apps (in [`mobile/`](mobile/README.md)) read it and send messages through it

## Install on the device

Start from Raspberry Pi OS Lite (or DietPi).

```bash
git clone https://github.com/FELIXJZN/uplink-9.git
cd uplink-9
./install.sh --deps --boot
sudo reboot
```

`--deps` installs the system packages (including pygame for the touch screen) and gives you access to the
screen, touchscreen and audio. `--boot` makes the device log in on its own screen and open Uplink-9.
Leave `--boot` off to just get the `uplink` command.

Already installed v0.2 (the first touch build)? Update from its SYSTEM menu, or `git pull` and run
`./install.sh --deps --boot` again. Your settings, webhooks and holotapes carry over.

To get a normal shell, choose **POWER > EXIT TO SHELL**. Type `uplink` to go back.
SSH sessions always get a normal shell.

## Touch and screens

Uplink-9 picks how to draw by itself:

- **On the device's own screen** it runs in **graphics mode**: drawn straight to the display with pygame
  (no desktop needed), with scanlines.
- **Over SSH**, in a desktop terminal or on Windows it runs in **text mode**: the same screens in any terminal.
- **Touchscreen found** (or the first time you touch the screen): **touch controls**.
  - tap an option to pick it; tap anywhere else for ENTER (pause a tape, skip the boot)
  - swipe up and down to scroll
  - buttons along the bottom come from each screen's hints: BACK, PAUSE, EJECT, ▲ ▼, ◄ ►
  - an on-screen keyboard appears whenever a screen wants typing
  - a physical keyboard keeps working alongside

Change it in **SETTINGS > SCREEN & TOUCH** (mode, touch, text size, scanlines, full screen) or for one run:

```bash
uplink --gui          # graphics mode     uplink --tty        text mode
uplink --touch        # touch controls on uplink --no-touch   off
uplink --plain        # plain mode for this run only (not saved)
uplink --no-boot      # skip the boot sequence
uplink --detect       # show which mode and touchscreen it would use, then exit
```

Touchscreens are found from the kernel's input list (devices with absolute positions that sit on a
display, so touchpads don't count). If graphics mode can't open the screen it falls back to text mode
and says why on the boot screen.

### Bigger text in text mode

```bash
sudo apt install fonts-terminus
sudo dpkg-reconfigure console-setup    # pick Terminus, then 16x32
```

### CRT look in text mode (optional)

`uplink --crt` runs the terminal inside cool-retro-term for curved glass and scanlines.
Needs `sudo apt install cage cool-retro-term`. Plain mode in Accessibility is the opposite: green text only.

## Login

After boot you choose USER or ADMIN. The first ADMIN login asks you to choose a password.
Users get files, USB, messages, tapes and nodes; admin gets everything, including the shell.
Change it under **SETTINGS > USERS & LOGIN**, where you can also turn login off.

This locks the terminal, not Linux: give the Linux account its own strong password too,
because anyone who can SSH in can change the config.

Forgot the admin password? Over SSH, clear `"admin_pw"` in `~/.config/uplink/config.json`;
the next admin login asks for a new one.

## Phone link

The Uplink-9 iPhone and Apple Watch apps (separate repo, `uplink-9-mobile`) can read this
device's status and send messages through it.

1. **SETTINGS > PHONE LINK > LINK ON** (admin).
2. **SHOW PAIRING CODE**, then point the iPhone camera at it and open the link.

The phone reaches the device on port 8909, over Tailscale when both are on your tailnet, so it
works away from home too. Only someone with the pairing code can connect; **NEW PAIRING CODE**
locks out every phone paired before.

API, all with `Authorization: Bearer <token>`:

| Request | Returns |
|---|---|
| `GET /api/status` | vitals, condition, drives, nodes, VPN, unread count |
| `GET /api/messages` | threads with their last 30 messages |
| `POST /api/messages/<thread id>` with `{"text": "..."}` | sends a message |
| `GET /api/tapes` | holotapes |

## Updates

**SETTINGS > UPDATE FIRMWARE** checks GitHub, shows what changed, installs, and restarts.
The app folder is a git clone, so an update is a fast-forward. **ROLL BACK** returns to the version before the last update.

Two channels (**UPDATE CHANNEL** on that screen):

- **RELEASES** (default, safest): only versions you tag on GitHub. A half-finished push to `main` never reaches the device.
- **BRANCH**: every commit on a branch (`main` unless you change it).

Updates never go backwards, and they refuse to run if files were edited on the device.

To release an update: bump `VERSION` (for example `0.12-beta` to `0.13-beta`, shown as BETA 0.13), commit,
push to `main`, then tag it with the same number and push the tag:

```bash
git tag v0.13-beta
git push origin v0.13-beta
```

Every device sees it on its next check (and at boot if CHECK AT BOOT is on). From a shell:
`python3 -m uplink.updater` checks, `--apply` installs.

## Webhooks

**SETTINGS > WEBHOOKS > ADD WEBHOOK.** Discord and ntfy URLs are detected; anything else gets JSON:

```json
{"event": "usb.inserted", "summary": "USB inserted: STEMS", "device": "UPLINK-9",
 "host": "hackberry", "version": "2.0.0", "time": 1791378092, "data": {"device": "/dev/sda1"}}
```

Events: `boot`, `usb.inserted`, `usb.removed`, `file.copied`, `file.deleted`, `tape.recorded`,
`message.sent`, `node.down`, `node.up`, `vpn.changed`, `update.installed`. Each webhook picks its own events.

## Permissions

- **USB mounting** uses udisks2 and works without sudo for the user logged in on the device's screen.
- **Tailscale** without sudo: run once `sudo tailscale set --operator=$USER`.
- **Shutdown and reboot** work for the user logged in on the device's screen.

## Configuration

`~/.config/uplink/config.json`: nodes (name, host, MAC for Wake-on-LAN), rsync targets, webhooks, settings.
Tapes and messages live in `~/.local/share/uplink`.

## Keys

| Key | Does |
|---|---|
| Up / Down (or J / K, W / S) | Move |
| 1 to 9 | Pick that option straight away |
| Enter / Right / Space | Select, play/pause, send |
| Esc / Backspace / Left / Q | Back |
| Page Up / Page Down | Jump |
| Letters | Type in prompts, messages, notes and tape logs |
| Ctrl+U | Clear what you typed |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

Run them before tagging a release. The touch tests run without a screen (SDL's dummy driver) and
simulate taps and swipes.

## Run on a PC

Windows: double-click `run-windows.bat` for text mode, or run `run-windows.bat --gui --touch` from a
command prompt for the touch screen in a window (mouse clicks act as taps). Linux/macOS: `./install.sh`
then `uplink`. USB, VPN and power controls only work on the Linux device.

## License

GPL-3.0. See [LICENSE](LICENSE). You can use, change and share Uplink-9, but anything you distribute
that's built from it must stay open source under the same license.
