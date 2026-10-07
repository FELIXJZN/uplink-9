"""Uplink-9: 4RDEN Industries terminal."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
except OSError:
    __version__ = "0.0.0"


def version_label(v: str) -> str:
    """How a version is shown: '0.10-beta' -> 'BETA 0.10', '1.0' -> 'V1.0'."""
    v = (v or "").strip()
    if v.lower().endswith("-beta"):
        return "BETA " + v[:-5]
    return "V" + v
