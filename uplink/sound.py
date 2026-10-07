"""UI sounds in the style of an old green-screen terminal, synthesised (no recordings).

Each sound is built from a few layers: filtered noise for mechanical clicks, low tones for relays,
a sweep and a faint high whine for the CRT warming up. The same recipes live in the HTML simulator,
so both sound the same. WAVs are rendered once into the cache, then played with aplay (Linux)
or winsound (Windows).
"""
from __future__ import annotations

import math
import platform
import random
import shutil
import struct
import subprocess
import time
import wave

from .storage import CACHE_DIR

SR = 44100
VERSION = 2  # bump when the recipes change, so cached WAVs are re-rendered


class _Rng:
    """Tiny deterministic noise generator (same as the simulator's), so every render sounds identical."""
    def __init__(self, seed: int):
        self.s = seed or 1

    def __call__(self) -> float:
        self.s = (self.s * 16807) % 2147483647
        return self.s / 2147483647 * 2 - 1


def noise(dur, vol, lp=None, hp=None, tau=None, seed=1):
    n = int(dur * SR)
    r = _Rng(seed)
    a_lp = 1 - math.exp(-2 * math.pi * lp / SR) if lp else 1.0
    a_hp = 1 - math.exp(-2 * math.pi * hp / SR) if hp else 0.0
    lo = lo2 = 0.0
    out = []
    for i in range(n):
        x = r()
        if lp:
            lo += a_lp * (x - lo)
            x = lo
        if hp:
            lo2 += a_hp * (x - lo2)
            x = x - lo2
        env = math.exp(-i / SR / tau) if tau else 1.0
        atk = min(1.0, i / (0.001 * SR))
        out.append(x * vol * env * atk)
    return out


def tone(freq, dur, vol, wave_="square", tau=None, attack=0.002, to=None, trem=0):
    n = int(dur * SR)
    phase = 0.0
    out = []
    rel = int(0.015 * SR)
    for i in range(n):
        t = i / SR
        f = freq * (to / freq) ** (i / n) if to else freq
        phase += f / SR
        x = phase % 1.0
        if wave_ == "sine":
            s = math.sin(2 * math.pi * x)
        elif wave_ == "saw":
            s = 2 * x - 1
        else:
            s = 1.0 if x < 0.5 else -1.0
        env = math.exp(-t / tau) if tau else (min(1.0, (n - i) / rel) if rel else 1.0)
        atk = min(1.0, t / attack) if attack else 1.0
        tr = 0.5 + 0.5 * math.sin(2 * math.pi * trem * t) if trem else 1.0
        out.append(s * vol * env * atk * tr)
    return out


def mix(*layers):
    """layers: (offset_seconds, samples)."""
    length = max(int(off * SR) + len(s) for off, s in layers)
    out = [0.0] * length
    for off, s in layers:
        o = int(off * SR)
        for i, v in enumerate(s):
            out[o + i] += v
    return out


def _click(v: int):
    return mix((0, noise(.018, .55, lp=6500, hp=1400, tau=.004, seed=v + 1)),
               (0, tone(170 + v * 25, .03, .22, "sine", tau=.008)))


RECIPES = {
    "click_0": lambda: _click(0),                       # key press: mechanical, three variants
    "click_1": lambda: _click(1),
    "click_2": lambda: _click(2),
    "tick": lambda: noise(.010, .32, hp=2800, tau=.0025, seed=7),          # cursor moves
    "type": lambda: noise(.006, .3, hp=2200, tau=.0015, seed=11),         # a character prints
    "blip": lambda: mix((0, noise(.03, .5, lp=2600, tau=.008, seed=3)),    # select: relay chunk
                        (0, tone(95, .07, .35, tau=.02)),
                        (.012, noise(.012, .25, hp=2000, tau=.003, seed=5))),
    "clack": lambda: mix((0, noise(.05, .6, lp=1800, tau=.012, seed=13)),  # tape deck / switch
                         (0, tone(70, .09, .4, "sine", tau=.03)),
                         (.065, noise(.02, .35, lp=3000, tau=.005, seed=17))),
    "ok": lambda: tone(1050, .05, .16, tau=.03),
    "chirp": lambda: mix((0, tone(1300, .06, .15, tau=.04)), (.09, tone(1750, .08, .15, tau=.05))),
    "buzz": lambda: tone(150, .32, .2, trem=28),                          # error
    "rec": lambda: tone(800, .12, .2, "sine"),
    "stop": lambda: tone(600, .12, .2, "sine"),
    "hum": lambda: mix((0, tone(55, .5, .55, "sine", tau=.15)),           # CRT power on: thunk,
                       (0, noise(.08, .45, lp=400, tau=.03, seed=19)),     # warm-up sweep and the
                       (.05, tone(80, .9, .14, "sine", attack=.2, to=220)),  # faint high whine
                       (.1, tone(15700, 1.2, .025, "sine", attack=.3))),
    "off": lambda: mix((0, tone(300, .35, .3, "sine", to=40)),             # power off: collapse
                       (.3, noise(.02, .3, lp=2000, tau=.005, seed=23))),
}

_last = 0.0
_proc = None


def _file(name: str):
    path = CACHE_DIR / f"sounds-v{VERSION}" / f"{name}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        samples = RECIPES[name]()
        frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32000)) for v in samples)
        tmp = path.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(frames)
        tmp.replace(path)
    return path


def play(name: str) -> None:
    global _last, _proc
    if name == "click":
        name = f"click_{random.randrange(3)}"
    if name not in RECIPES:
        return
    now = time.monotonic()
    small = name.startswith(("click", "tick", "type"))
    if small and now - _last < .03:
        return
    _last = now
    try:
        path = _file(name)
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        elif shutil.which("aplay"):
            if small and _proc and _proc.poll() is None:
                return
            _proc = subprocess.Popen(["aplay", "-q", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # sound is never allowed to break the terminal


def warm() -> None:
    """Render every sound once, in the background at startup."""
    for name in RECIPES:
        try:
            _file(name)
        except OSError:
            pass
