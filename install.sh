#!/usr/bin/env bash
# Uplink-9 installer. Run it from inside the cloned repo:
#
#   ./install.sh            install for this user: Python environment + the 'uplink' command
#   ./install.sh --deps     also install system packages with apt (asks for sudo)
#   ./install.sh --boot     also boot straight into Uplink-9 on the device's own screen (asks for sudo)
#   ./install.sh --uninstall
#
# Flags can be combined:  ./install.sh --deps --boot

set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"
LAUNCHER="$BIN/uplink"
PROFILE_FILE="$HOME/.bash_profile"
GETTY_DIR="/etc/systemd/system/getty@tty1.service.d"
MARK_START="# >>> uplink boot >>>"
MARK_END="# <<< uplink boot <<<"

DEPS=0; BOOT=0; UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --deps) DEPS=1 ;;
    --boot) BOOT=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "Unknown option: $a"; exit 1 ;;
  esac
done

remove_profile_block() {
  if [ -f "$PROFILE_FILE" ] && grep -qF "$MARK_START" "$PROFILE_FILE"; then
    sed -i "/$MARK_START/,/$MARK_END/d" "$PROFILE_FILE"
  fi
}

if [ "$UNINSTALL" = 1 ]; then
  rm -f "$LAUNCHER"
  rm -rf "$REPO/.venv"
  remove_profile_block
  if [ -f "$GETTY_DIR/autologin.conf" ]; then
    sudo rm -f "$GETTY_DIR/autologin.conf" && sudo systemctl daemon-reload
    echo "Removed console auto-login."
  fi
  echo "Uplink-9 removed. Your settings, tapes and messages are kept in ~/.config/uplink and ~/.local/share/uplink."
  exit 0
fi

# 1. System packages (optional)
if [ "$DEPS" = 1 ]; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv git udisks2 alsa-utils rsync openssh-client
  echo "Optional extras: tailscale (tailscale.com/download), croc (sudo apt install croc), twingate."
fi

command -v python3 >/dev/null || { echo "python3 is missing. Run: ./install.sh --deps"; exit 1; }
command -v git >/dev/null || echo "Note: git is missing, so firmware updates won't work. Run: ./install.sh --deps"

# 2. Python environment
if [ ! -x "$REPO/.venv/bin/python" ]; then
  python3 -m venv "$REPO/.venv" || { echo "Could not create the Python environment. Run: ./install.sh --deps"; exit 1; }
fi
"$REPO/.venv/bin/python" -m pip install -q --upgrade pip
"$REPO/.venv/bin/python" -m pip install -q -r "$REPO/requirements.txt"

# 3. The 'uplink' command
mkdir -p "$BIN"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Starts Uplink-9. 'uplink --crt' runs it inside cool-retro-term for the CRT look (needs cage + cool-retro-term).
if [ "\${1:-}" = "--crt" ]; then
  shift
  exec cage -- cool-retro-term --fullscreen -e "\$0" "\$@"
fi
cd "$REPO" || exit 1
# Restart after a crash (up to 3 times in a row); a normal exit drops to the shell.
crashes=0
while true; do
  "$REPO/.venv/bin/python" -m uplink "\$@" && exit 0
  crashes=\$((crashes + 1))
  if [ "\$crashes" -ge 3 ]; then
    echo "Uplink-9 stopped after 3 crashes. Details: ~/.local/share/uplink/crash.log  Type 'uplink' to try again."
    exit 1
  fi
  echo "Uplink-9 crashed. Restarting in 3 seconds (Ctrl+C for a shell)..."
  sleep 3
done
EOF
chmod +x "$LAUNCHER"
echo "Installed. Start it with:  uplink"

# 4. Boot straight into the terminal (optional)
if [ "$BOOT" = 1 ]; then
  sudo mkdir -p "$GETTY_DIR"
  sudo tee "$GETTY_DIR/autologin.conf" >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
  sudo systemctl daemon-reload

  remove_profile_block
  if [ ! -f "$PROFILE_FILE" ]; then
    # bash skips ~/.profile once ~/.bash_profile exists, so keep loading it
    printf '[ -f "$HOME/.profile" ] && . "$HOME/.profile"\n' > "$PROFILE_FILE"
  fi
  cat >> "$PROFILE_FILE" <<EOF
$MARK_START
# Start Uplink-9 on the device's own screen only, never in an SSH session.
# Choose EXIT TO SHELL in the POWER menu to get a normal shell; type 'uplink' to go back.
if [ "\$(tty)" = "/dev/tty1" ] && [ -z "\${SSH_CONNECTION:-}" ]; then
  "$LAUNCHER"
fi
$MARK_END
EOF
  echo "Boot: on. The device logs in on its own screen and opens Uplink-9. Reboot to try it."
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Note: $BIN is not on your PATH yet. Log out and back in once." ;;
esac
