"""Uplink-9: 4RDEN Industries terminal.

Copyright (C) 2026 4rden (FELIXJZN)

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, version 3. See LICENSE.
"""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
except OSError:   # installed with pip: the VERSION file isn't next to the code
    try:
        from importlib.metadata import version as _dist_version
        __version__ = _dist_version("uplink-9").replace("b0", "-beta")
    except Exception:
        __version__ = "0.0.0"


def version_label(v: str) -> str:
    """How a version is shown: '0.10-beta' -> 'BETA 0.10', '1.0' -> 'V1.0'."""
    v = (v or "").strip()
    if v.lower().endswith("-beta"):
        return "BETA " + v[:-5]
    return "V" + v
