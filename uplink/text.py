"""Text helpers shared by both screen backends."""
from __future__ import annotations

import textwrap


def wrap_lines(lines, width: int) -> list[str]:
    """Wrap each line to width, keeping blank lines as paragraph breaks."""
    out: list[str] = []
    width = max(1, width)
    for line in lines:
        if not line.strip():
            out.append("")
        else:
            out.extend(textwrap.wrap(line, width) or [""])
    return out


def leader(label: str, cols: int, width: int = 22) -> str:
    """'LABEL ........ ' padded to fit narrow screens."""
    width = max(len(label) + 3, min(width, cols - 16))
    return f"{label} ".ljust(width, ".") + " "
