"""Config and data storage. Config lives in ~/.config/uplink, data in ~/.local/share/uplink."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import wave
from datetime import datetime
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
    "update_channel": "RELEASES",  # RELEASES: only tagged releases (v0.12-beta ...). BRANCH: every commit on the branch
    "device_name": "UPLINK-9",
    "aspect": "FILL",
    # screen (graphics mode is pygame on the device's own display; text mode is any terminal)
    "interface": "AUTO",     # AUTO: graphics on the device's own screen, text over SSH. GRAPHICS / TEXT to force
    "touch": "AUTO",         # AUTO: touch controls when a touchscreen is found. ON / OFF to force
    "text_size": "AUTO",     # graphics mode: AUTO / SMALL / LARGE
    "scanlines": "ON",       # graphics mode: CRT scanlines (off in plain mode)
    "fullscreen": "AUTO",    # graphics mode: AUTO = full screen on the device, a window on a desktop
    # login
    "login_at_boot": "ON",
    "default_role": "ADMIN",      # used when login at boot is off
    "admin_pw": "",               # pbkdf2 hash, never the password itself
    "soon_show": "ON",
    "soon_name": "CLASSIFIED",
    "discord_invite": "https://discord.gg/YOUR-INVITE",
    # phone link (iPhone and Watch apps)
    "link": "OFF",
    "link_port": 8909,
    "link_token": "",
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
            migrated = migrate_v02_config(data)
            self.update(data)
            if migrated:
                for old in V02_KEYS:
                    self.pop(old, None)
        else:
            migrated = False
        self._clean()
        if migrated:
            LOAD_PROBLEMS.append("SETTINGS FROM UPLINK-9 V0.2 WERE CARRIED OVER.")
            self.save()

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
                                     "admin_pw", "soon_name", "discord_invite", "link_token")}
        self.clear()
        self.update(json.loads(json.dumps(DEFAULTS)))
        self.update(keep)
        self.save()


# ---------------------------------------------------------------- carrying over Uplink-9 v0.2 (the touch build)
V02_KEYS = ("callsign", "plain_mode", "effects", "update", "usb", "messages", "gui")


def migrate_v02_config(data: dict) -> bool:
    """v0.2 kept settings in the same config.json with other names. Translate them in place."""
    if not any(k in data for k in ("callsign", "plain_mode", "effects", "gui")):
        return False
    words = {"auto": "AUTO", "gui": "GRAPHICS", "tty": "TEXT", True: "ON", False: "OFF"}
    if data.get("callsign"):
        data["device_name"] = str(data["callsign"]).upper()[:16]
    data["plain"] = "ON" if data.get("plain_mode") else "OFF"
    if "interface" in data:
        data["interface"] = words.get(data["interface"], "AUTO")
    if "touch" in data:
        data["touch"] = words.get(data["touch"], "AUTO")
    gui = data.get("gui") if isinstance(data.get("gui"), dict) else {}
    if "fullscreen" in gui:
        data["fullscreen"] = words.get(gui["fullscreen"], "AUTO")
    fx = data.get("effects") if isinstance(data.get("effects"), dict) else {}
    if fx.get("typing") is False or fx.get("boot_sequence") is False:
        data["animations"] = "OFF"
    if fx.get("scanlines") is False:
        data["scanlines"] = "OFF"
    up = data.get("update") if isinstance(data.get("update"), dict) else {}
    data["update_channel"] = "BRANCH" if up.get("channel") == "branch" else "RELEASES"
    if up.get("branch"):
        data["update_branch"] = str(up["branch"])
    if up.get("check_on_boot") is False:
        data["update_check_boot"] = "OFF"
    hooks = data.get("webhooks") if isinstance(data.get("webhooks"), list) else []
    for h in hooks:
        if isinstance(h, dict) and isinstance(h.get("format"), str):
            h["format"] = h["format"].upper()
    return True


def _wav_secs(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / max(1, w.getframerate()))
    except (OSError, EOFError, wave.Error):
        return 0


def _epoch(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except (TypeError, ValueError):
        return 0


def import_v02_tapes(folder: Path, copy_audio: bool = False) -> int:
    """Tapes saved by v0.2 (<id>.json with title/text, and <id>.wav) become regular tapes here."""
    if not folder.is_dir():
        return 0
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in TAPES_DIR.glob("*.json")}
    count = 0
    for src in sorted(folder.glob("*.json")):
        old = _read(src, None)
        if not (isinstance(old, dict) and old.get("id")):
            continue
        tid = "v02-" + str(old["id"])
        if tid in have:
            continue
        audio = ""
        if old.get("audio"):
            wav = folder / str(old["audio"])
            if wav.exists():
                if copy_audio:
                    shutil.copy2(wav, TAPES_DIR / f"{tid}.wav")
                    wav = TAPES_DIR / f"{tid}.wav"
                audio = str(wav)
        lines = str(old.get("text") or "").splitlines()
        secs = _wav_secs(Path(audio)) if audio else max(1, sum(len(l) for l in lines) // 12)
        save_tape({"id": tid, "name": str(old.get("title") or "OLD TAPE").upper()[:24], "lines": lines,
                   "secs": secs, "audio": audio, "quality": "STANDARD" if audio else "",
                   "created": _epoch(old.get("created", ""))})
        count += 1
    return count


def import_usb_tapes(root: Path) -> int:
    """Tapes from a USB drive: our own exports (UPLINK_TAPES/NAME.txt + NAME.wav) and v0.2 exports
    (UPLINK-9/holotapes). Tapes already here are skipped. Returns how many were new."""
    count = import_v02_tapes(root / "UPLINK-9" / "holotapes", copy_audio=True)
    folder = root / "UPLINK_TAPES"
    if not folder.is_dir():
        return count
    TAPES_DIR.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in TAPES_DIR.glob("*.json")}
    for txt in sorted(folder.glob("*.txt")):
        try:
            text = txt.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tid = "usb-" + hashlib.sha1((txt.stem + "\n" + text).encode()).hexdigest()[:10]
        if tid in have:
            continue
        audio = ""
        wav = txt.with_suffix(".wav")
        if wav.exists():
            shutil.copy2(wav, TAPES_DIR / f"{tid}.wav")
            audio = str(TAPES_DIR / f"{tid}.wav")
        lines = text.splitlines()
        secs = _wav_secs(Path(audio)) if audio else max(1, sum(len(l) for l in lines) // 12)
        save_tape({"id": tid, "name": txt.stem.upper()[:24], "lines": lines, "secs": secs, "audio": audio,
                   "quality": "STANDARD" if audio else "", "created": int(txt.stat().st_mtime)})
        count += 1
    return count


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
    import_v02_tapes(DATA_DIR / "holotapes")       # v0.2 kept its tapes here
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
