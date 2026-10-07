# Uplink-9

A 4RDEN Industries terminal for a handheld Linux computer (HackberryPi CM5, uConsole, or any Raspberry Pi).
It boots straight into a green-phosphor terminal: no desktop, no browser.

- **Files:** browse, view, copy, move, rename, delete, new folders and notes
- **USB drives:** plug one in and it shows up, mounts, and can be ejected safely
- **Transfer:** Taildrop, rsync or croc
- **Messages:** threads that post to a webhook; ntfy threads are two-way
- **Nodes:** ping your machines, Wake-on-LAN, open an SSH shell
- **VPN:** switch between Tailscale, Twingate or off (one at a time)
- **Holotape:** record from the microphone, play back, export to USB
- **Settings:** display color, accessibility, webhooks, firmware updates from GitHub

## Install on the device

Start from Raspberry Pi OS Lite (or DietPi).

```bash
git clone https://github.com/YOUR-NAME/uplink-9.git
cd uplink-9
./install.sh --deps --boot
sudo reboot
```

`--deps` installs the system packages and `--boot` makes the device log in on its own screen and open Uplink-9.
Leave `--boot` off to just get the `uplink` command.

To get a normal shell, choose **POWER > EXIT TO SHELL**. Type `uplink` to go back.
SSH sessions always get a normal shell.

### Bigger text on the console

```bash
sudo apt install fonts-terminus
sudo dpkg-reconfigure console-setup    # pick Terminus, then 16x32
```

### CRT look (optional)

`uplink --crt` runs the terminal inside cool-retro-term for curved glass and scanlines.
Needs `sudo apt install cage cool-retro-term`. Plain mode in Accessibility is the opposite: green text only.

## Updates

**SETTINGS > UPDATE FIRMWARE** checks GitHub, shows what changed, installs, and restarts.
The app folder is a git clone, so an update is a fast-forward of `main`. **ROLL BACK** returns to the version before the last update.

To release an update: bump `VERSION`, commit, push to `main`. Every device sees it on its next check
(and at boot if CHECK AT BOOT is on).

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
| Up / Down (or J / K) | Move |
| Enter / Right | Select, play/pause, send |
| Esc / Backspace / Left | Back |
| Page Up / Page Down | Jump |
| Letters | Type in prompts, messages, notes and tape logs |

## Run on a PC

Windows: double-click `run-windows.bat`. Linux/macOS: `./install.sh` then `uplink`.
USB, VPN and power controls only work on the Linux device.
