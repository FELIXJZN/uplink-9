"""Screen drawing, phosphor effects and input widgets.

Everything is keyboard-only and works without arrow keys, so it is usable on a
BlackBerry-style keyboard:  j/k or w/s move, ENTER or space selects, q goes back,
and 1-9 jump straight to a menu entry.
"""
from __future__ import annotations

import curses
import random
import textwrap
import time

ESC = 27
BACK_KEYS = {ord("q"), ord("Q"), ESC, curses.KEY_BACKSPACE, 127, 8, curses.KEY_LEFT}
UP_KEYS = {curses.KEY_UP, ord("k"), ord("w"), ord("K"), ord("W")}
DOWN_KEYS = {curses.KEY_DOWN, ord("j"), ord("s"), ord("J"), ord("S")}
SELECT_KEYS = {curses.KEY_ENTER, 10, 13, ord(" "), curses.KEY_RIGHT}
PAGE_UP_KEYS = {curses.KEY_PPAGE, ord("b")}


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


class Screen:
    def __init__(self, stdscr, cfg: dict):
        self.s = stdscr
        self.cfg = cfg
        self.plain = bool(cfg.get("plain_mode") or cfg.get("_cli_plain"))
        self.skip_effects = False
        self.s.keypad(True)
        self._cursor(0)

        self.normal = curses.A_NORMAL
        self.bright = curses.A_BOLD
        self.dim = curses.A_NORMAL
        if not self.plain and curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            green = curses.color_pair(1)
            self.normal = green
            self.bright = green | curses.A_BOLD
            self.dim = green | curses.A_DIM
            self.s.bkgd(" ", green)
        self.reverse = self.bright | curses.A_REVERSE

    # ---- basics -----------------------------------------------------------

    @staticmethod
    def _cursor(visibility: int) -> None:
        try:
            curses.curs_set(visibility)
        except curses.error:
            pass

    def effect(self, name: str) -> bool:
        """True when a visual effect should play (off in plain mode or once skipped)."""
        if self.plain or self.skip_effects:
            return False
        return bool(self.cfg.get("effects", {}).get(name, True))

    def size(self) -> tuple[int, int]:
        return self.s.getmaxyx()

    def put(self, y: int, x: int, text: str, attr=None) -> None:
        """addstr that clips to the screen instead of crashing."""
        h, w = self.size()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        room = w - x - (1 if y == h - 1 else 0)  # the bottom-right cell can't be written
        if room <= 0:
            return
        try:
            self.s.addstr(y, x, text[:room], self.normal if attr is None else attr)
        except curses.error:
            pass

    def frame(self, title: str, hint: str = "") -> None:
        """Clear and draw the title bar and the key-hint line."""
        self.s.erase()
        h, w = self.size()
        bar = f" {self.cfg.get('callsign', 'UPLINK-9')} // {title} "
        self.put(0, 0, bar.ljust(w), self.reverse)
        if hint and h > 2:
            self.put(h - 1, 0, hint, self.dim)

    def body_rows(self) -> int:
        h, _ = self.size()
        return max(1, h - 3)

    # ---- effects ----------------------------------------------------------

    def type_text(self, y: int, x: int, text: str, attr=None) -> None:
        """Print text one character at a time. Any key finishes all typing instantly."""
        if not self.effect("typing"):
            self.put(y, x, text, attr)
            self.s.refresh()
            return
        delay = self.cfg.get("effects", {}).get("typing_delay_ms", 8) / 1000
        self.s.nodelay(True)
        try:
            for i, ch in enumerate(text):
                self.put(y, x + i, ch, attr)
                self.s.refresh()
                if self.s.getch() != -1:
                    self.skip_effects = True
                    self.put(y, x, text, attr)
                    break
                time.sleep(delay)
        finally:
            self.s.nodelay(False)
        self.s.refresh()

    def pause(self, seconds: float) -> None:
        if self.effect("typing"):
            self.s.refresh()
            time.sleep(seconds)

    def flicker(self, times: int = 2) -> None:
        if not self.effect("flicker"):
            return
        for _ in range(times):
            self.s.bkgd(" ", self.reverse)
            self.s.refresh()
            time.sleep(0.03)
            self.s.bkgd(" ", self.normal)
            self.s.refresh()
            time.sleep(random.uniform(0.03, 0.12))

    # ---- widgets ----------------------------------------------------------

    def menu(self, title: str, items: list[str], hint: str = "", start: int = 0):
        """Show a list and return the chosen index, or None when backed out."""
        if not items:
            self.pager(title, ["(nothing here)"])
            return None
        sel = max(0, min(start, len(items) - 1))
        hint = hint or "j/k move  ENTER pick  1-9 jump  q back"
        while True:
            self.frame(title, hint)
            _, w = self.size()
            rows = self.body_rows() - 1
            top = sel - rows + 1 if sel >= rows else 0
            for row, idx in enumerate(range(top, min(len(items), top + rows))):
                num = f"{idx + 1}" if idx < 9 else " "
                selected = idx == sel
                line = f"{'>' if selected else ' '} {num} {items[idx]}"
                self.put(2 + row, 0, line.ljust(w - 1) if selected else line,
                         self.reverse if selected else self.normal)
            self.s.refresh()
            key = self.s.getch()
            if key in UP_KEYS:
                sel = (sel - 1) % len(items)
            elif key in DOWN_KEYS:
                sel = (sel + 1) % len(items)
            elif key in SELECT_KEYS:
                return sel
            elif key in BACK_KEYS:
                return None
            elif ord("1") <= key <= ord("9") and key - ord("1") < len(items):
                return key - ord("1")

    def pager(self, title: str, lines, hint: str = "") -> None:
        """Scrollable read-only text. Any back/enter key closes it."""
        if isinstance(lines, str):
            lines = lines.splitlines()
        pos = 0
        hint = hint or "j/k scroll  q/ENTER close"
        while True:
            self.frame(title, hint)
            _, w = self.size()
            wrapped = wrap_lines(lines, w - 2)
            rows = self.body_rows()
            pos = max(0, min(pos, len(wrapped) - rows))
            for i, line in enumerate(wrapped[pos:pos + rows]):
                self.put(2 + i, 1, line)
            self.s.refresh()
            key = self.s.getch()
            if key in DOWN_KEYS:
                pos += 1
            elif key in UP_KEYS:
                pos -= 1
            elif key == curses.KEY_NPAGE:
                pos += rows
            elif key in PAGE_UP_KEYS:
                pos -= rows
            elif key == curses.KEY_RESIZE:
                continue
            elif key in BACK_KEYS or key in (10, 13, curses.KEY_ENTER):
                return
            elif key == ord(" "):
                if pos + rows >= len(wrapped):
                    return
                pos += rows

    def type_out(self, title: str, lines) -> None:
        """'Play' text like a recording: typed out, then shown in the pager."""
        if isinstance(lines, str):
            lines = lines.splitlines()
        if self.effect("typing"):
            self.frame(title, "any key: skip")
            _, w = self.size()
            wrapped = wrap_lines(lines, w - 2)
            for i, line in enumerate(wrapped[: self.body_rows()]):
                self.type_text(2 + i, 1, line)
            self.skip_effects = False
        self.pager(title, lines)

    def confirm(self, title: str, question: str) -> bool:
        while True:
            self.frame(title, "y yes   n no")
            _, w = self.size()
            for i, line in enumerate(wrap_lines([question], w - 2)):
                self.put(2 + i, 1, line, self.bright)
            self.s.refresh()
            key = self.s.getch()
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N")) or key in BACK_KEYS:
                return False

    def busy(self, title: str, text: str) -> None:
        """Show a status line while something slow runs."""
        self.frame(title)
        self.put(2, 1, text, self.bright)
        self.s.refresh()

    def prompt(self, title: str, label: str, initial: str = "", max_len: int = 2000):
        """Single text field (wraps over several lines). Returns the text, or None on ESC."""
        buf = list(initial)
        self._cursor(1)
        try:
            while True:
                self.frame(title, "ENTER done   ESC cancel")
                h, w = self.size()
                self.put(2, 1, label, self.bright)
                width = max(1, w - 4)
                text = "".join(buf)
                lines = [text[i:i + width] for i in range(0, max(1, len(text)), width)] or [""]
                visible = lines[-max(1, h - 6):]
                for i, line in enumerate(visible):
                    self.put(4 + i, 2, line)
                try:
                    self.s.move(4 + len(visible) - 1, 2 + len(visible[-1]))
                except curses.error:
                    pass
                self.s.refresh()
                try:
                    key = self.s.get_wch()
                except curses.error:
                    continue
                if key in ("\n", "\r") or key == curses.KEY_ENTER:
                    return "".join(buf).strip()
                if key == "\x1b":
                    return None
                if key in ("\x7f", "\b") or key == curses.KEY_BACKSPACE:
                    if buf:
                        buf.pop()
                elif key == "\x15":  # Ctrl+U clears the line
                    buf.clear()
                elif isinstance(key, str) and key.isprintable() and len(buf) < max_len:
                    buf.append(key)
        finally:
            self._cursor(0)
