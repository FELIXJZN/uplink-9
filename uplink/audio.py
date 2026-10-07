"""Holotape audio: record from the microphone with arecord, play back with aplay."""
from __future__ import annotations

import array
import math
import os
import shutil
import signal
import subprocess
import threading
import wave

QUALITY = {  # rate, channels
    "LO-FI": (8000, 1),
    "STANDARD": (22050, 1),
    "HI-FI": (44100, 2),
}


def can_record() -> bool:
    if not shutil.which("arecord"):
        return False
    try:
        p = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
        return "card" in p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def can_play() -> bool:
    return shutil.which("aplay") is not None


class Recorder:
    def __init__(self, path: str, quality: str = "STANDARD"):
        self.path = path
        self.rate, self.channels = QUALITY.get(quality, QUALITY["STANDARD"])
        self.level = 0.0
        self.frames = 0
        self.error = ""
        self._proc = None
        self._thread = None

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(self.rate), "-c", str(self.channels)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self.error = str(e)
            return False
        self._wav = wave.open(self.path, "wb")
        self._wav.setnchannels(self.channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.rate)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self):
        chunk = 1024 * 2 * self.channels
        while True:
            data = self._proc.stdout.read(chunk)
            if not data:
                break
            self._wav.writeframes(data)
            self.frames += len(data) // (2 * self.channels)
            samples = array.array("h", data[: len(data) - len(data) % 2])
            if samples:
                rms = math.sqrt(sum(s * s for s in samples[::4]) / max(1, len(samples[::4])))
                self.level = min(100.0, rms / 80)  # rough scale to 0..100
        if self._proc.poll() not in (None, 0, -signal.SIGTERM) and self._proc.stderr:
            self.error = self._proc.stderr.read().decode(errors="ignore")[:80]

    def stop(self) -> float:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self._wav.close()
        except Exception:
            pass
        return self.frames / self.rate


class Player:
    def __init__(self, path: str):
        self.path = path
        self._proc = None
        self.paused = False

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(["aplay", "-q", self.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def pause(self, on: bool) -> None:
        if self.alive():
            os.kill(self._proc.pid, signal.SIGSTOP if on else signal.SIGCONT)
            self.paused = on

    def stop(self) -> None:
        if self.alive():
            if self.paused:
                os.kill(self._proc.pid, signal.SIGCONT)
            self._proc.terminate()


def wav_seconds(path: str) -> float:
    try:
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except (OSError, wave.Error, EOFError):
        return 0.0
