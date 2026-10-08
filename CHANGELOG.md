# Changelog

## Beta 0.11

- Phone link for the new Uplink-9 iPhone and Apple Watch apps (SETTINGS > PHONE LINK, admin only)
  - A small HTTP API on port 8909: device vitals, drives, nodes, VPN, messages, holotapes,
    and sending messages from the phone
  - Every request needs the pairing token; pair by scanning the QR code with the iPhone camera
  - NEW PAIRING CODE revokes every paired phone
  - Messages sent from the phone are marked as such and go out through the thread's webhook

## Beta 0.10

- Uplink-9 is now numbered as a beta. This is the same code as 2.2.0 below; the earlier
  numbers are kept here for history. Versions show as BETA 0.10 on the device.

## 2.2.0

- Field Unit: a wrist-computer mode on the login screen with four tabs
  - VITALS: battery, CPU temperature and load, memory, storage, uptime, a 32-second load graph
    and an overall condition, all read live from the device every second
  - CARGO: internal storage and USB drives with free space, mount and eject
  - LOGS: holotapes (playback returns to the Field Unit) and the latest messages
  - SIGNAL: Wi-Fi strength, VPN tunnel and every node with signal bars
- Runs with user rights; ESC returns to the login screen

## 2.1.0

- Login at boot: USER or ADMIN. The first admin login sets a password (stored as a salted hash).
  Three wrong passwords lock the terminal for 30 seconds.
- Users can't open webhooks, firmware, users & login, device name or restore defaults, can't switch
  the VPN, open SSH shells, browse the whole system, restart the terminal or exit to the shell.
  Ctrl+Q only quits for an admin. Locked items show ADMIN instead of hiding.
- POWER > LOG OUT returns to the login screen
- Settings > Aspect ratio: fill, 1:1, 4:3, 16:10 or 16:9; the terminal letterboxes itself
- A coming-soon option on the login screen with a Discord invite and a scannable QR code;
  its name and link are set in Settings > Users & login
- New dependency: segno (QR codes)

## 2.0.2

- New sounds in the style of an old terminal, synthesised: mechanical key clicks (three variants),
  relay chunk on select, a tick per printed character, CRT power-on thunk with warm-up sweep and
  faint high whine, power-off collapse, low error buzz
- Text prints faster at NORMAL speed, so booting takes about half as long
- The HTML simulator uses the same sound recipes, so both sound the same

## 2.0.1

Stability and speed, no new features.

- An error now shows an error screen and is logged to ~/.local/share/uplink/crash.log instead of closing the terminal
- The launcher restarts the terminal after a crash (up to 3 times)
- A typo in config.json is set aside as config.json.broken instead of being overwritten
- Hand-edited nodes and webhooks with missing fields are repaired instead of crashing
- Boot checks run side by side: no more long waits without network
- Pressing ENTER during boot no longer replays the boot over the main menu
- Nodes are pinged in parallel
- Faster output for rsync, Taildrop and croc
- Long lines in the file viewer wrap instead of pushing text off screen
- An empty note is no longer saved as an empty file
- Half-copied files are removed if a copy fails; broken links are skipped
- Copying to USB now says to eject before unplugging
- Pulling out a stick while its page is open no longer leaves a stale screen
- ASCII symbols on the Linux console, whose font lacks a few characters
- Unchanged frames are skipped and folder listings are cached
- Test suite: python -m pytest tests

## 2.0.0

- Native terminal app: no browser, boots straight into Uplink-9 on the device's screen
- USB drives: detect, mount, browse, copy, move, rename, delete, eject safely
- Holotape recording from the microphone, playback, export to USB
- Messages linked to webhooks; two-way with ntfy
- Nodes with ping, Wake-on-LAN and SSH shell
- VPN switching between Tailscale and Twingate
- Accessibility menu with plain (realism) mode
- Webhooks with per-hook events and formats (JSON, Discord, ntfy)
- Firmware updates from GitHub with rollback
