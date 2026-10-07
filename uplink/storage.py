"""Config and data storage. Config lives in ~/.config/uplink, data in ~/.local/share/uplink."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "uplink"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "uplink"
TAPES_DIR = DATA_DIR / "tapes"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "uplink"

DEFAULTS = {
    # display
    "color": "GREEN",
    "clock": "24H",
    # accessibility
    "plain": "OFF",          # realism mode: green text only, every effect off
    "animations": "ON",
    "cursor_blink": "ON",
    "sounds": "ON",
    "key_clicks": "ON",
    "text_speed": "NORMAL",
    # holotape
    "quality": "STANDARD",
    "mic": "ON",
    "speed": "NORMAL",
    "autoname": "ON",
    # system
    "usb_automount": "ON",
    "update_check_boot": "ON",
    "update_branch": "main",
    "device_name": "UPLINK-9",
    # networking
    "nodes": [
        {"name": "PVE-1", "host": "pve-1", "role": "ROUTER", "mac": ""},
        {"name": "PVE-2", "host": "pve-2", "role": "GAMING", "mac": ""},
        {"name": "PVE-3", "host": "pve-3", "role": "STORAGE", "mac": ""},
        {"name": "REDRABBIT", "host": "redrabbit", "role": "HOME", "mac": ""},
    ],
    "rsync_targets": ["pve-3:/tank/inbox"],
    "webhooks": [],
    "previous_commit": "",
}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Config(dict):
    path = CONFIG_DIR / "config.json"

    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.update(_read(self.path, {}))

    def save(self) -> None:
        _write(self.path, dict(self))

    def reset(self) -> None:
        keep = {k: self[k] for k in ("nodes", "rsync_targets", "webhooks", "previous_commit", "device_name")}
        self.clear()
        self.update(json.loads(json.dumps(DEFAULTS)))
        self.update(keep)
        self.save()


def load_messages():
    return _read(DATA_DIR / "messages.json", [
        {"id": "self", "name": "NOTES TO SELF", "hook": "", "msgs": []},
    ])


def save_messages(threads) -> None:
    _write(DATA_DIR / "messages.json", threads)


def load_tapes():
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    tapes = []
    for p in sorted(TAPES_DIR.glob("*.json")):
        t = _read(p, None)
        if t:
            t["_path"] = str(p)
            tapes.append(t)
    return tapes


def save_tape(tape: dict) -> Path:
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in tape.items() if not k.startswith("_")}
    path = Path(tape.get("_path") or TAPES_DIR / f"{tape['id']}.json")
    _write(path, data)
    return path
