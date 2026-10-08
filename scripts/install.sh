#!/bin/sh
# UPLINK-9 installer. Run from inside the cloned repo:
#
#   ./scripts/install.sh              launcher + default config
#   ./scripts/install.sh --deps       apt-install pygame, fonts, git, alsa-utils, udisks2 (needs sudo)
#   ./scripts/install.sh --autostart  start UPLINK on tty1 whenever you log in there
#   ./scripts/install.sh --autologin  log in on tty1 automatically at boot (needs sudo)
#
# Use --autostart --autologin together to boot straight into the terminal.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/uplink"
PROFILE="$HOME/.profile"
[ -f "$HOME/.bash_profile" ] && PROFILE="$HOME/.bash_profile"
MARK="# >>> uplink-9 autostart >>>"

DEPS=0; AUTOSTART=0; AUTOLOGIN=0
for arg in "$@"; do
  case "$arg" in
    --deps) DEPS=1 ;;
    --autostart) AUTOSTART=1 ;;
    --autologin) AUTOLOGIN=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

say() { printf '[uplink] %s\n' "$1"; }

if [ "$DEPS" = 1 ]; then
  say "installing packages"
  sudo apt-get update
  sudo apt-get install -y git python3 python3-pygame fonts-dejavu-core alsa-utils udisks2
  # screen (video), touchscreen + keys (input) and audio access without root
  sudo usermod -aG video,input,audio "$(id -un)"
  say "added you to the video/input/audio groups (takes effect after reboot)"
fi

command -v python3 >/dev/null || { say "python3 is required"; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { say "python 3.9+ required"; exit 1; }
command -v git >/dev/null || say "warning: git missing - updates won't work (use --deps)"
python3 -c 'import pygame' 2>/dev/null || say "warning: pygame missing - no touch/graphics, text mode only (use --deps)"

mkdir -p "$BIN"
cat > "$BIN/uplink" <<EOF
#!/bin/sh
cd "$REPO" && exec python3 -m uplink "\$@"
EOF
chmod +x "$BIN/uplink"
say "launcher: $BIN/uplink"

if [ ! -f "$CONF_DIR/config.json" ]; then
  mkdir -p "$CONF_DIR"
  cp "$REPO/config.example.json" "$CONF_DIR/config.json"
  say "config: $CONF_DIR/config.json"
fi

if [ "$AUTOSTART" = 1 ]; then
  if grep -q "$MARK" "$PROFILE" 2>/dev/null; then
    say "autostart already in $PROFILE"
  else
    cat >> "$PROFILE" <<EOF

$MARK
# Launch UPLINK-9 on the first console. Exit it to get a normal shell.
# Set UPLINK_NO_AUTOSTART=1 to skip it.
if [ "\$(tty)" = "/dev/tty1" ] && [ -z "\${UPLINK_NO_AUTOSTART:-}" ]; then
  "$BIN/uplink"
fi
# <<< uplink-9 autostart <<<
EOF
    say "autostart added to $PROFILE"
  fi
fi

if [ "$AUTOLOGIN" = 1 ]; then
  USER_NAME="$(id -un)"
  say "enabling autologin on tty1 for $USER_NAME"
  sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
  sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I \$TERM
EOF
  sudo systemctl daemon-reload
  say "autologin on - reboot to boot straight into UPLINK-9"
fi

say "done. run: uplink   (or uplink --plain)"
