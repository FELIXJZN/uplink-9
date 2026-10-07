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
    "aspect": "FILL",
    # login
    "login_at_boot": "ON",
    "default_role": "ADMIN",      # used when login at boot is off
    "admin_pw": "",               # pbkdf2 hash, never the password itself
    "soon_show": "ON",
    "soon_name": "CLASSIFIED",
    "discord_invite": "https://discord.gg/YOUR-INVITE",
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


LOAD_PROBLEMS: list[str] = []   # shown to the user once the terminal is up


def _read(path: Path, default):
    """Read JSON. A missing file gives the default; a broken one is set aside, never overwritten."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return default
    try:
        return json.loads(text)
    except ValueError as e:
        backup = path.with_name(path.name + ".broken")
        try:
            os.replace(path, backup)
        except OSError:
            pass
        LOAD_PROBLEMS.append(f"{path.name} HAD AN ERROR (LINE {getattr(e, 'lineno', '?')}). SAVED AS {backup.name}, USING DEFAULTS.")
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
        data = _read(self.path, {})
        if isinstance(data, dict):
            self.update(data)
        self._clean()

    def _clean(self) -> None:
        """Repair hand-edited values so a missing field can never crash a screen."""
        for key, default in DEFAULTS.items():
            if type(self.get(key)) is not type(default):
                LOAD_PROBLEMS.append(f"CONFIG: '{key}' HAS THE WRONG TYPE, USING THE DEFAULT.")
                self[key] = json.loads(json.dumps(default))
        nodes = []
        for n in self["nodes"]:
            if isinstance(n, dict) and n.get("host"):
                nodes.append({"name": str(n.get("name") or n["host"]).upper()[:12], "host": str(n["host"]),
                              "role": str(n.get("role", "")).upper(), "mac": str(n.get("mac", ""))})
            else:
                LOAD_PROBLEMS.append("CONFIG: SKIPPED A NODE WITHOUT A HOST.")
        self["nodes"] = nodes
        from .webhooks import EVENTS, FORMATS  # local import: webhooks imports this package
        hooks = []
        for h in self["webhooks"]:
            if not (isinstance(h, dict) and str(h.get("url", "")).startswith(("http://", "https://"))):
                LOAD_PROBLEMS.append("CONFIG: SKIPPED A WEBHOOK WITHOUT A VALID URL.")
                continue
            hooks.append({
                "id": str(h.get("id") or os.urandom(4).hex()), "name": str(h.get("name") or "WEBHOOK").upper(),
                "url": h["url"], "format": h.get("format") if h.get("format") in FORMATS else "JSON",
                "events": [e for e in h.get("events", EVENTS) if e in EVENTS], "enabled": bool(h.get("enabled", True)),
                "last": str(h.get("last", "")),
            })
        self["webhooks"] = hooks
        self["rsync_targets"] = [str(t) for t in self["rsync_targets"] if ":" in str(t)]

    def save(self) -> None:
        _write(self.path, dict(self))

    def reset(self) -> None:
        keep = {k: self[k] for k in ("nodes", "rsync_targets", "webhooks", "previous_commit", "device_name",
                                     "admin_pw", "soon_name", "discord_invite")}
        self.clear()
        self.update(json.loads(json.dumps(DEFAULTS)))
        self.update(keep)
        self.save()


def load_messages():
    data = _read(DATA_DIR / "messages.json", None)
    threads = []
    for t in data if isinstance(data, list) else []:
        if isinstance(t, dict) and t.get("name"):
            t.setdefault("id", os.urandom(4).hex())
            t.setdefault("hook", "")
            t["msgs"] = [m for m in t.get("msgs", []) if isinstance(m, dict) and "t" in m]
            threads.append(t)
    return threads or [{"id": "self", "name": "NOTES TO SELF", "hook": "", "msgs": []}]


def save_messages(threads) -> None:
    for t in threads:
        t["msgs"] = t["msgs"][-500:]   # keep the file small
    _write(DATA_DIR / "messages.json", threads)


def load_tapes():
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    tapes = []
    for p in sorted(TAPES_DIR.glob("*.json")):
        t = _read(p, None)
        if isinstance(t, dict) and t.get("id") and t.get("name"):
            t.setdefault("lines", [])
            t.setdefault("secs", 0)
            t["_path"] = str(p)
            tapes.append(t)
    return tapes


def save_tape(tape: dict) -> Path:
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in tape.items() if not k.startswith("_")}
    path = Path(tape.get("_path") or TAPES_DIR / f"{tape['id']}.json")
    _write(path, data)
    return path
