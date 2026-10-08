"""Holotapes: dated text or audio logs, playable back on the terminal.

Each tape is <id>.json (and <id>.wav for audio) in <data dir>/holotapes.
Audio uses arecord/aplay (alsa-utils) when they are installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import config as config_mod

EXPORT_DIR = "UPLINK-9/holotapes"


def tape_dir() -> Path:
    path = config_mod.data_dir() / "holotapes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def save_tape(directory: Path, title: str, text: str = "", audio: str | None = None,
              tape_id: str | None = None) -> dict:
    tape = {
        "id": tape_id or new_id(),
        "title": title,
        "created": datetime.now().isoformat(timespec="seconds"),
        "text": text,
        "audio": audio,
    }
    (directory / f"{tape['id']}.json").write_text(json.dumps(tape, indent=2), encoding="utf-8")
    return tape


def list_tapes(directory: Path) -> list[dict]:
    tapes = []
    for path in directory.glob("*.json"):
        try:
            tape = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(tape, dict) and "id" in tape:
            tapes.append(tape)
    return sorted(tapes, key=lambda t: t.get("created", ""), reverse=True)


def update_tape(directory: Path, tape: dict) -> None:
    (directory / f"{tape['id']}.json").write_text(json.dumps(tape, indent=2), encoding="utf-8")


def delete_tape(directory: Path, tape: dict) -> None:
    (directory / f"{tape['id']}.json").unlink(missing_ok=True)
    if tape.get("audio"):
        (directory / tape["audio"]).unlink(missing_ok=True)


def _tape_files(directory: Path, tape: dict) -> list[Path]:
    files = [directory / f"{tape['id']}.json"]
    if tape.get("audio") and (directory / tape["audio"]).exists():
        files.append(directory / tape["audio"])
    return files


def export_tapes(directory: Path, drive_root: Path) -> int:
    """Copy every tape onto a drive under UPLINK-9/holotapes. Returns how many."""
    dest = drive_root / EXPORT_DIR
    dest.mkdir(parents=True, exist_ok=True)
    tapes = list_tapes(directory)
    for tape in tapes:
        for src in _tape_files(directory, tape):
            shutil.copy2(src, dest / src.name)
    return len(tapes)


def import_tapes(drive_root: Path, directory: Path) -> int:
    """Copy tapes from a drive that aren't already here. Returns how many were new."""
    src_dir = drive_root / EXPORT_DIR
    if not src_dir.is_dir():
        return 0
    have = {t["id"] for t in list_tapes(directory)}
    count = 0
    for tape in list_tapes(src_dir):
        if tape["id"] in have:
            continue
        for src in _tape_files(src_dir, tape):
            shutil.copy2(src, directory / src.name)
        count += 1
    return count


def audio_available() -> bool:
    return bool(shutil.which("arecord") and shutil.which("aplay"))


# ---- screen ---------------------------------------------------------------

def _label(tape: dict) -> str:
    stamp = tape.get("created", "")[5:16].replace("T", " ")
    kind = " [AUDIO]" if tape.get("audio") else ""
    return f"{tape.get('title', '?').upper()}{kind}  {stamp}"


def _record_audio(scr, directory: Path, title: str) -> None:
    tape_id = new_id()
    wav = f"{tape_id}.wav"
    try:
        proc = subprocess.Popen(["arecord", "-q", "-f", "cd", "-t", "wav", str(directory / wav)],
                                stderr=subprocess.PIPE)
    except OSError as exc:
        scr.pager("RECORD", [f"Could not start recorder: {exc}"])
        return
    start = time.monotonic()
    try:
        while proc.poll() is None:
            secs = int(time.monotonic() - start)
            blink = "●" if secs % 2 == 0 or scr.plain else " "
            scr.status("RECORDING", [f"{blink} REC  {secs // 60:02d}:{secs % 60:02d}", "",
                                     title.upper()], button="STOP")
            if scr.poll_stop(0.25):
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    if not (directory / wav).exists():
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        scr.pager("RECORD", ["Recording failed.", err.strip()])
        return
    note = scr.prompt("RECORD", "NOTE FOR THIS TAPE (optional):") or ""
    save_tape(directory, title, note, audio=wav, tape_id=tape_id)


def _play_audio(scr, directory: Path, tape: dict) -> None:
    try:
        proc = subprocess.Popen(["aplay", "-q", str(directory / tape["audio"])])
    except OSError as exc:
        scr.pager("PLAY", [f"Could not start player: {exc}"])
        return
    scr.status("PLAYING", [f"▶ {tape.get('title', '').upper()}"], button="STOP")
    while proc.poll() is None:
        if scr.poll_stop(0.1):
            proc.terminate()
            break


def _tape_menu(scr, directory: Path, tape: dict) -> None:
    while True:
        options = ["PLAY"]
        if tape.get("audio"):
            options.append("PLAY AUDIO")
        options += ["RENAME", "DELETE"]
        choice = scr.menu(tape.get("title", "TAPE").upper(), options)
        if choice is None:
            return
        action = options[choice]
        if action == "PLAY":
            header = [f"HOLOTAPE: {tape.get('title', '').upper()}",
                      f"RECORDED: {tape.get('created', '').replace('T', ' ')}", ""]
            scr.type_out("PLAYBACK", header + (tape.get("text") or "(no text)").splitlines())
        elif action == "PLAY AUDIO":
            _play_audio(scr, directory, tape)
        elif action == "RENAME":
            title = scr.prompt("RENAME", "NEW TITLE:", tape.get("title", ""))
            if title:
                tape["title"] = title
                update_tape(directory, tape)
        elif action == "DELETE":
            if scr.confirm("DELETE", f"Erase holotape '{tape.get('title')}'?"):
                delete_tape(directory, tape)
                return


def run(scr, cfg, ctx):
    directory = tape_dir()
    sel = 0
    while True:
        tapes = list_tapes(directory)
        actions = ["+ RECORD TEXT LOG"]
        if audio_available():
            actions.append("+ RECORD AUDIO")
        items = actions + [_label(t) for t in tapes]
        sel = scr.menu("HOLOTAPES", items, start=sel)
        if sel is None:
            return
        if sel < len(actions):
            title = scr.prompt("RECORD", "TAPE TITLE:")
            if not title:
                continue
            if actions[sel] == "+ RECORD AUDIO":
                _record_audio(scr, directory, title)
            else:
                text = scr.prompt("RECORD", "LOG ENTRY:")
                if text is not None:
                    save_tape(directory, title, text)
        else:
            _tape_menu(scr, directory, tapes[sel - len(actions)])
