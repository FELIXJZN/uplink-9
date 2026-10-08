"""Touchscreen detection from the kernel's input device list.

/proc/bus/input/devices lists every input device with capability bitmasks.
A touchscreen is a device that reports absolute X/Y positions (EV_ABS with
ABS_X or ABS_MT_POSITION_X) and has INPUT_PROP_DIRECT set, meaning it sits on
top of a display. Touchpads report positions too but lack INPUT_PROP_DIRECT.
"""
from __future__ import annotations

import struct
from pathlib import Path

INPUT_PROP_DIRECT = 1
EV_ABS = 3
ABS_X = 0x00
ABS_MT_POSITION_X = 0x35

WORD_BITS = struct.calcsize("P") * 8  # the kernel prints bitmasks in native longs


def parse_bitmask(text: str, word_bits: int = WORD_BITS) -> int:
    value = 0
    for word in text.split():
        value = (value << word_bits) | int(word, 16)
    return value


def parse_devices(text: str) -> list[dict]:
    devices, current = [], {}
    for line in text.splitlines() + [""]:
        line = line.strip()
        if not line:
            if current:
                devices.append(current)
                current = {}
            continue
        kind, _, rest = line.partition(": ")
        if kind == "N" and rest.startswith("Name="):
            current["name"] = rest[5:].strip('"')
        elif kind == "B":
            key, _, mask = rest.partition("=")
            current[key.lower()] = mask
        elif kind == "H":
            current["handlers"] = rest.partition("=")[2].split()
    return devices


def is_touchscreen(dev: dict, word_bits: int = WORD_BITS) -> bool:
    bit = lambda key, n: (parse_bitmask(dev.get(key, "0"), word_bits) >> n) & 1
    if not bit("ev", EV_ABS):
        return False
    has_position = bit("abs", ABS_X) or bit("abs", ABS_MT_POSITION_X)
    if not has_position:
        return False
    if bit("prop", INPUT_PROP_DIRECT):
        return True
    # Some older drivers don't set the property but name themselves clearly.
    name = dev.get("name", "").lower()
    return "touchscreen" in name or "touch screen" in name


def detect(path: str = "/proc/bus/input/devices") -> list[str]:
    """Names of touchscreens found (empty list = none, or not Linux)."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    return [d.get("name", "touchscreen") for d in parse_devices(text) if is_touchscreen(d)]
