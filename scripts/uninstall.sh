#!/bin/sh
# Remove the UPLINK-9 launcher, autostart hook and tty1 autologin.
# Your config (~/.config/uplink) and data (~/.local/share/uplink) are kept.
set -eu

rm -f "$HOME/.local/bin/uplink"
for f in "$HOME/.profile" "$HOME/.bash_profile"; do
  [ -f "$f" ] && sed -i '/# >>> uplink-9 autostart >>>/,/# <<< uplink-9 autostart <<</d' "$f"
done
if [ -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]; then
  sudo rm /etc/systemd/system/getty@tty1.service.d/autologin.conf
  sudo systemctl daemon-reload
fi
echo "[uplink] removed. config and data were left in place."
