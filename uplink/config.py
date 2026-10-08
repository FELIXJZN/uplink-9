"""Loading and saving the user config, plus where UPLINK keeps its data.

Config lives in ~/.config/uplink/config.json, data in ~/.local/share/uplink.
Both can be overridden with UPLINK_CONFIG_DIR / UPLINK_DATA_DIR (used by tests).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "callsign": "UPLINK-9",
    # Accessibility / plain mode: no colours, no typing, no flicker, no boot animation.
    "plain_mode": False,
    "effects": {
        "boot_sequence": True,
        "typing": True,
        "typing_delay_ms": 8,
        "flicker": True,
    },
    "update": {
        "remote": "origin",
        # "tags": only install tagged releases (v0.2.0, ...). Safer.
        # "branch": follow the newest commit on `branch`.
        "channel": "tags",
        "branch": "main",
        "check_on_boot": True,
    },
    "usb": {
        "mount_roots": ["/media", "/run/media", "/mnt"],
    },
    # Each webhook: {"name": "...", "url": "...", "format": "json" | "discord" | "ntfy"}
    "webhooks": [],
    "messages": {
        # Name of a webhook that outgoing messages get relayed to ("" = store locally only).
        "relay_webhook": "",
    },
}


def config_dir() -> Path:
    env = os.environ.get("UPLINK_CONFIG_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "uplink"


def data_dir() -> Path:
    env = os.environ.get("UPLINK_DATA_DIR")
    if env:
        path = Path(env)
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "uplink"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def deep_merge(base: dict, override: dict) -> dict:
    """Return base with override applied on top, recursing into nested dicts."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(user, dict):
            raise ValueError("config root must be an object")
    except (OSError, ValueError) as exc:
        cfg = copy.deepcopy(DEFAULTS)
        cfg["_error"] = f"config.json unreadable, using defaults ({exc})"
        return cfg
    return deep_merge(DEFAULTS, user)


def save(cfg: dict, path: Path | None = None) -> None:
    """Write the config atomically. Keys starting with '_' are runtime-only and skipped."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
