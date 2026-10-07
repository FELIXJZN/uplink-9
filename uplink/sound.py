"""UI sounds. Small WAV files are generated once, then played with aplay (Linux) or winsound (Windows)."""
from __future__ import annotations

import math
import platform
import shutil
import struct
import subprocess
import time
import wave

from .storage import CACHE_DIR

RATE = 22050
SOUNDS = {
    # name: list of (freq, seconds, volume, wave) segments
    "click": [(2000, .012, .25, "square")],
    "tick":  [(1250, .02, .2, "square")],
    "blip":  [(950, .045, .3, "square")],
    "chirp": [(880, .07, .3, "square"), (0, .02, 0, "square"), (1320, .09, .3, "square")],
    "buzz":  [(110, .28, .35, "saw")],
    "clack": [(120, .08, .5, "square")],
    "ok":    [(660, .04, .25, "square")],
    "rec":   [(440, .15, .3, "sine")],
    "stop":  [(330, .15, .3, "sine")],
    "hum":   [("sweep", .9, .45, "sine")],
}

_last = 0.0
_proc = None


def _sample(kind: str, phase: float) -> float:
    x = phase % 1.0
    if kind == "sine":
        return math.sin(2 * math.pi * x)
    if kind == "saw":
        return 2 * x - 1
    return 1.0 if x < .5 else -1.0


def _render(segments) -> bytes:
    frames = bytearray()
    for freq, secs, vol, kind in segments:
        n = int(RATE * secs)
        phase = 0.0
        for i in range(n):
            t = i / n
            f = 40 + 100 * t if freq == "sweep" else freq
            env = min(1.0, i / 60) * (1 - t) ** 2 if freq != "sweep" else math.sin(math.pi * t)
            phase += f / RATE
            v = _sample(kind, phase) * vol * env if f else 0.0
            frames += struct.pack("<h", int(max(-1, min(1, v)) * 32000))
    return bytes(frames)


def _file(name: str):
    path = CACHE_DIR / "sounds" / f"{name}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(_render(SOUNDS[name]))
    return path


def play(name: str) -> None:
    global _last, _proc
    if name not in SOUNDS:
        return
    now = time.monotonic()
    if name in ("click", "tick") and now - _last < .035:
        return
    _last = now
    try:
        path = _file(name)
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        elif shutil.which("aplay"):
            if _proc and _proc.poll() is None and name in ("click", "tick"):
                return
            _proc = subprocess.Popen(["aplay", "-q", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # sound is never allowed to break the terminal


def warm() -> None:
    for name in SOUNDS:
        try:
            _file(name)
        except OSError:
            pass
