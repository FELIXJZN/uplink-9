"""Graphical backend (pygame): green-phosphor screen with touch support.

Draws straight to the device's display (KMS/DRM on a bare console, or a
window on a desktop). Every screen works by touch alone - tap to pick,
swipe to scroll, BACK button in the title bar, on-screen keyboard for
text - and a physical keyboard keeps working alongside.

Has the same methods as ui.Screen, so every app section runs on either.
"""
from __future__ import annotations

import random
import time

import pygame

from .system import ExitToShell
from .text import wrap_lines

PHOSPHOR = {"fg": (70, 255, 125), "dim": (35, 150, 75), "bg": (3, 12, 6),
            "glow": (14, 70, 32), "edge": (30, 120, 60)}
PLAIN = {"fg": (255, 255, 255), "dim": (220, 220, 220), "bg": (0, 0, 0),
         "glow": None, "edge": (220, 220, 220)}

NORMAL, BRIGHT, DIM, REVERSE = "normal", "bright", "dim", "reverse"
FONTS = "dejavusansmono,liberationmono,notomono,ubuntumono,consolas,couriernew,monospace"
CONSOLE_DRIVERS = {"kmsdrm", "fbcon", "directfb"}

UP = {pygame.K_UP, pygame.K_k, pygame.K_w}
DOWN = {pygame.K_DOWN, pygame.K_j, pygame.K_s}
SELECT = {pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_RIGHT}
BACK = {pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_LEFT, pygame.K_q}
ENTER = {pygame.K_RETURN, pygame.K_KP_ENTER}
DRAG_START_PX = 12

KEYBOARD = {
    "abc": ["1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm,./"],
    "ABC": ["1234567890", "QWERTYUIOP", "ASDFGHJKL_", "ZXCVBNM?!:"],
    "sym": ["!@#$%^&*()", "-_=+[]{}\\|", ":;\"'<>?~`'", "/.,@&€£$%#"],
}


class DisplayUnavailable(Exception):
    pass


def open_display(cfg: dict):
    """Open the screen. Returns (surface, fullscreen, driver name)."""
    try:
        pygame.display.init()
        pygame.font.init()
    except pygame.error as exc:
        raise DisplayUnavailable(str(exc)) from exc
    driver = pygame.display.get_driver()
    gui_cfg = cfg.get("gui", {})
    want = gui_cfg.get("fullscreen", "auto")
    fullscreen = driver in CONSOLE_DRIVERS if want == "auto" else bool(want)
    try:
        if fullscreen:
            surface = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            w, h = gui_cfg.get("window", [800, 480])
            surface = pygame.display.set_mode((int(w), int(h)), pygame.RESIZABLE)
    except pygame.error as exc:
        pygame.quit()
        raise DisplayUnavailable(str(exc)) from exc
    pygame.display.set_caption("UPLINK-9")
    return surface, fullscreen, driver


class GuiScreen:
    def __init__(self, surface, cfg: dict, touch: bool = False,
                 fullscreen: bool = False, driver: str = ""):
        self.display = surface
        self.cfg = cfg
        self.plain = bool(cfg.get("plain_mode") or cfg.get("_cli_plain"))
        self.touch = touch
        self.fullscreen = fullscreen
        self.driver = driver
        self.skip_effects = False
        self.normal, self.bright, self.dim, self.reverse = NORMAL, BRIGHT, DIM, REVERSE
        self.c = PLAIN if self.plain else PHOSPHOR
        self._pending: list = []
        self._press = None
        self._dragging = False
        self._last_y = 0
        self._back_rect = None
        pygame.key.set_repeat(400, 40)
        if fullscreen:
            pygame.mouse.set_visible(False)
        self._layout()

    # ---- layout -----------------------------------------------------------

    def _layout(self) -> None:
        self.W, self.H = self.display.get_size()
        self.canvas = pygame.Surface((self.W, self.H))
        size = int(self.cfg.get("gui", {}).get("font_size") or 0)
        if not size:  # touch needs bigger targets; keep ~26+ columns on narrow screens
            size = min(self.H // 20, self.W // 16) if self.touch else min(self.H // 28, self.W // 40)
        size = max(14, min(size, 64))
        self.font = pygame.font.SysFont(FONTS, size)
        self.cw = max(1, self.font.size("M")[0])
        self.lh = max(1, self.font.get_linesize())
        self.bar_h = int(self.lh * 1.7) if self.touch else self.lh
        self.body_top = self.bar_h + self.lh // 2
        self.scan = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        for y in range(0, self.H, 3):
            pygame.draw.line(self.scan, (0, 0, 0, 70), (0, y), (self.W, y))

    def size(self) -> tuple[int, int]:
        return self.H // self.lh, self.W // self.cw

    def describe(self) -> str:
        mode = "TOUCH" if self.touch else "KEYS"
        return f"{self.W}x{self.H} {mode}"

    def effect(self, name: str) -> bool:
        if self.plain or self.skip_effects:
            return False
        return bool(self.cfg.get("effects", {}).get(name, True))

    def _mark_touch(self) -> None:
        if not self.touch:  # a touch arrived that detection missed: switch modes
            self.touch = True
            self._layout()

    # ---- drawing ----------------------------------------------------------

    def text(self, text: str, x: int, y: int, style=NORMAL, color=None) -> None:
        if not text:
            return
        if style == REVERSE:
            w = self.font.size(text)[0]
            pygame.draw.rect(self.canvas, self.c["fg"], (x, y, w, self.lh))
            self.canvas.blit(self.font.render(text, True, self.c["bg"]), (x, y))
            return
        col = color or (self.c["dim"] if style == DIM else self.c["fg"])
        if style == BRIGHT and self.c["glow"] and self.effect("scanlines"):
            glow = self.font.render(text, True, self.c["glow"])
            self.canvas.blit(glow, (x + 1, y))
            self.canvas.blit(glow, (x - 1, y + 1))
        self.canvas.blit(self.font.render(text, True, col), (x, y))

    def fit(self, text: str, width: int) -> str:
        """Trim text to fit width pixels."""
        max_chars = max(1, width // self.cw)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "~"

    def button(self, rect, label: str, active: bool = False) -> None:
        rect = pygame.Rect(rect)
        radius = max(3, self.lh // 5)
        if active:
            pygame.draw.rect(self.canvas, self.c["fg"], rect, border_radius=radius)
        else:
            pygame.draw.rect(self.canvas, self.c["edge"], rect, 2, border_radius=radius)
        label = self.fit(label, rect.w - 4)
        tw = self.font.size(label)[0]
        x = rect.x + (rect.w - tw) // 2
        y = rect.y + (rect.h - self.lh) // 2
        self.text(label, x, y, color=self.c["bg"] if active else self.c["fg"])

    def put(self, y: int, x: int, text: str, attr=None) -> None:
        rows, cols = self.size()
        if 0 <= y < rows and 0 <= x < cols:
            text = text[: cols - x]
            # overwrite like a real terminal: clear the cells first
            self.canvas.fill(self.c["bg"], (x * self.cw, y * self.lh, len(text) * self.cw, self.lh))
            self.text(text, x * self.cw, y * self.lh, attr or NORMAL)

    def frame(self, title: str, hint: str = "", back: bool = True) -> None:
        self.canvas.fill(self.c["bg"])
        pygame.draw.rect(self.canvas, self.c["fg"], (0, 0, self.W, self.bar_h))
        self._back_rect = None
        right = self.W
        if back and self.touch:
            bw = self.font.size(" BACK ")[0] + self.cw
            pad = max(3, self.bar_h // 8)
            self._back_rect = pygame.Rect(self.W - bw - pad, pad, bw, self.bar_h - 2 * pad)
            pygame.draw.rect(self.canvas, self.c["bg"], self._back_rect,
                             border_radius=max(3, self.lh // 5))
            self.text("BACK", self._back_rect.x + (bw - self.font.size("BACK")[0]) // 2,
                      self._back_rect.y + (self._back_rect.h - self.lh) // 2)
            right = self._back_rect.x
        bar = f" {self.cfg.get('callsign', 'UPLINK-9')} // {title}"
        if self.font.size(bar)[0] > right - self.cw:
            bar = f" {title}"  # narrow screen: the section name matters most
        bar = self.fit(bar, right - self.cw)
        self.text(bar, 0, (self.bar_h - self.lh) // 2, color=self.c["bg"])
        if hint and not self.touch:
            self.text(self.fit(hint, self.W), 0, self.H - self.lh, DIM)

    def refresh(self) -> None:
        self.display.blit(self.canvas, (0, 0))
        if self.effect("scanlines"):
            self.display.blit(self.scan, (0, 0))
        pygame.display.flip()

    # ---- input ------------------------------------------------------------

    def _translate(self, ev):
        T = pygame
        if ev.type == T.QUIT:
            return ("quit",)
        if ev.type == T.KEYDOWN:
            return ("key", ev.key, getattr(ev, "unicode", ""))
        if ev.type in (T.FINGERDOWN, T.FINGERUP, T.FINGERMOTION):
            self._mark_touch()
            return None
        if ev.type == T.MOUSEBUTTONDOWN and ev.button == 1:
            if getattr(ev, "touch", False):
                self._mark_touch()
            self._press, self._last_y, self._dragging = ev.pos, ev.pos[1], False
            return None
        if ev.type == T.MOUSEMOTION and self._press:
            if not self._dragging and abs(ev.pos[1] - self._press[1]) > DRAG_START_PX:
                self._dragging = True
            if self._dragging:
                dy, self._last_y = ev.pos[1] - self._last_y, ev.pos[1]
                return ("drag", dy) if dy else None
            return None
        if ev.type == T.MOUSEBUTTONUP and ev.button == 1 and self._press:
            dragged, self._press, self._dragging = self._dragging, None, False
            return None if dragged else ("tap", ev.pos)
        if ev.type == T.MOUSEWHEEL:
            return ("wheel", -ev.y)
        if ev.type in (T.VIDEORESIZE, T.WINDOWSIZECHANGED):
            self.display = pygame.display.get_surface()
            self._layout()
            return ("resize",)
        return None

    def wait_event(self, timeout: float | None = None):
        """Next input event, or None after `timeout` seconds. Window close exits."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            for ev in pygame.event.get():
                out = self._translate(ev)
                if out:
                    self._pending.append(out)
            if self._pending:
                out = self._pending.pop(0)
                if out[0] == "quit":
                    raise ExitToShell()
                return out
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                ev = pygame.event.wait(max(1, int(left * 1000)))
            else:
                ev = pygame.event.wait()
            if ev.type != pygame.NOEVENT:
                out = self._translate(ev)
                if out:
                    self._pending.append(out)

    def _hit_back(self, ev) -> bool:
        return ev[0] == "tap" and self._back_rect is not None and self._back_rect.collidepoint(ev[1])

    # ---- effects ----------------------------------------------------------

    def type_text(self, y: int, x: int, text: str, attr=None) -> None:
        if not self.effect("typing"):
            self.put(y, x, text, attr)
            self.refresh()
            return
        delay = self.cfg.get("effects", {}).get("typing_delay_ms", 8) / 1000
        for i, ch in enumerate(text):
            self.put(y, x + i, ch, attr)
            self.refresh()
            ev = self.wait_event(delay)
            if ev and ev[0] in ("key", "tap"):
                self.skip_effects = True
                self.put(y, x + i + 1, text[i + 1:], attr)
                break
        self.refresh()

    def pause(self, seconds: float) -> None:
        if self.effect("typing"):
            self.refresh()
            ev = self.wait_event(seconds)
            if ev and ev[0] in ("key", "tap"):
                self.skip_effects = True

    def flicker(self, times: int = 2) -> None:
        if not self.effect("flicker"):
            return
        for _ in range(times):
            self.display.fill(self.c["glow"] or self.c["fg"])
            pygame.display.flip()
            time.sleep(0.03)
            self.refresh()
            time.sleep(random.uniform(0.03, 0.12))

    # ---- geometry (shared by drawing and tap handling) ---------------------

    def _menu_geometry(self):
        item_h = int(self.lh * (1.9 if self.touch else 1.3))
        bottom = self.H - (self.lh // 2 if self.touch else int(self.lh * 1.4))
        visible = max(1, (bottom - self.body_top) // item_h)
        return item_h, visible

    def _menu_rects(self, count: int, scroll: int):
        item_h, visible = self._menu_geometry()
        gap = max(2, item_h // 8)
        return [(pygame.Rect(self.cw // 2, self.body_top + row * item_h,
                             self.W - self.cw, item_h - gap), idx)
                for row, idx in enumerate(range(scroll, min(count, scroll + visible)))]

    def _footer_rects(self, count: int):
        gap = max(4, self.cw // 2)
        h = int(self.lh * 1.9)
        w = (self.W - gap * (count + 1)) // count
        y = self.H - h - gap
        return [pygame.Rect(gap + i * (w + gap), y, w, h) for i in range(count)]

    def _keyboard_layout(self, layer: str):
        """[(rect, action, label)] for the on-screen keyboard."""
        top = int(self.H * 0.47)
        gap = max(3, self.cw // 4)
        rows = KEYBOARD[layer]
        kh = (self.H - top - gap * 6) // 5
        keys = []
        for r, row in enumerate(rows):
            kw = (self.W - gap * (len(row) + 1)) / len(row)
            y = top + r * (kh + gap)
            for i, ch in enumerate(row):
                rect = pygame.Rect(int(gap + i * (kw + gap)), y, int(kw), kh)
                keys.append((rect, ("char", ch), ch))
        specials = [("shift", "Aa" if layer == "abc" else "aA", 1.3),
                    ("sym", "abc" if layer == "sym" else "#+=", 1.3),
                    ("space", "SPACE", 3.6), ("del", "DEL", 1.4), ("ok", "OK", 1.5)]
        total = self.W - gap * (len(specials) + 1)
        weight = sum(s[2] for s in specials)
        x, y = gap, top + 4 * (kh + gap)
        for action, label, wt in specials:
            w = int(total * wt / weight)
            keys.append((pygame.Rect(int(x), y, w, kh), (action,), label))
            x += w + gap
        return keys

    # ---- widgets ----------------------------------------------------------

    def menu(self, title: str, items: list[str], hint: str = "", start: int = 0):
        if not items:
            self.pager(title, ["(nothing here)"])
            return None
        sel = max(0, min(start, len(items) - 1))
        scroll, follow, drag = 0, True, 0.0
        while True:
            self.frame(title, hint or "j/k move  ENTER pick  1-9 jump  q back")
            item_h, visible = self._menu_geometry()
            if follow:
                if sel < scroll:
                    scroll = sel
                elif sel >= scroll + visible:
                    scroll = sel - visible + 1
            scroll = max(0, min(scroll, len(items) - visible))
            rects = self._menu_rects(len(items), scroll)
            for rect, idx in rects:
                label = f"{idx + 1}  {items[idx]}" if idx < 9 else f"   {items[idx]}"
                selected = idx == sel and not (self.touch and not follow)
                if selected:
                    pygame.draw.rect(self.canvas, self.c["fg"], rect, border_radius=max(3, self.lh // 5))
                elif self.touch:
                    pygame.draw.rect(self.canvas, self.c["edge"], rect, 2, border_radius=max(3, self.lh // 5))
                self.text(self.fit(label, rect.w - self.cw), rect.x + self.cw // 2,
                          rect.y + (rect.h - self.lh) // 2,
                          color=self.c["bg"] if selected else None)
            if scroll > 0:
                self.text("▲", self.W - self.cw * 2, self.body_top - self.lh // 2, DIM)
            if scroll + visible < len(items):
                self.text("▼ more", self.W - self.cw * 7,
                          rects[-1][0].bottom, DIM)
            self.refresh()

            ev = self.wait_event()
            if ev[0] == "key":
                key, ch = ev[1], ev[2]
                if key in UP:
                    sel, follow = (sel - 1) % len(items), True
                elif key in DOWN:
                    sel, follow = (sel + 1) % len(items), True
                elif key in SELECT:
                    return sel
                elif key in BACK:
                    return None
                elif ch and ch in "123456789" and int(ch) - 1 < len(items):
                    return int(ch) - 1
            elif ev[0] == "tap":
                if self._hit_back(ev):
                    return None
                for rect, idx in rects:
                    if rect.collidepoint(ev[1]):
                        return idx
            elif ev[0] == "drag":
                drag += ev[1]
                steps = int(drag / item_h)
                if steps:
                    scroll, drag, follow = scroll - steps, drag - steps * item_h, False
            elif ev[0] == "wheel":
                scroll, follow = scroll + ev[1], False

    def pager(self, title: str, lines, hint: str = "") -> None:
        if isinstance(lines, str):
            lines = lines.splitlines()
        pos, drag = 0, 0.0
        while True:
            self.frame(title, hint or "j/k scroll  q/ENTER close")
            wrapped = wrap_lines(lines, (self.W - 2 * self.cw) // self.cw)
            buttons = self._footer_rects(3) if self.touch else []
            bottom = buttons[0].top - self.lh // 3 if buttons else self.H - int(self.lh * 1.4)
            rows = max(1, (bottom - self.body_top) // self.lh)
            pos = max(0, min(pos, len(wrapped) - rows))
            for i, line in enumerate(wrapped[pos:pos + rows]):
                self.text(line, self.cw, self.body_top + i * self.lh)
            if buttons:
                for rect, label in zip(buttons, ("UP", "DOWN", "CLOSE")):
                    self.button(rect, label, active=label == "CLOSE")
            self.refresh()

            ev = self.wait_event()
            if ev[0] == "key":
                key = ev[1]
                if key in DOWN:
                    pos += 1
                elif key in UP:
                    pos -= 1
                elif key in (pygame.K_PAGEDOWN,):
                    pos += rows
                elif key in (pygame.K_PAGEUP, pygame.K_b):
                    pos -= rows
                elif key == pygame.K_SPACE:
                    if pos + rows >= len(wrapped):
                        return
                    pos += rows
                elif key in BACK or key in ENTER:
                    return
            elif ev[0] == "tap":
                if self._hit_back(ev):
                    return
                if buttons:
                    if buttons[0].collidepoint(ev[1]):
                        pos -= max(1, rows - 1)
                    elif buttons[1].collidepoint(ev[1]):
                        pos += max(1, rows - 1)
                    elif buttons[2].collidepoint(ev[1]):
                        return
            elif ev[0] == "drag":
                drag += ev[1]
                steps = int(drag / self.lh)
                if steps:
                    pos, drag = pos - steps, drag - steps * self.lh
            elif ev[0] == "wheel":
                pos += ev[1] * 3

    def type_out(self, title: str, lines) -> None:
        if isinstance(lines, str):
            lines = lines.splitlines()
        if self.effect("typing"):
            self.frame(title, "any key: skip")
            wrapped = wrap_lines(lines, (self.W - 2 * self.cw) // self.cw)
            first_row = self.body_top // self.lh + 1
            for i, line in enumerate(wrapped[: self.size()[0] - first_row - 1]):
                self.type_text(first_row + i, 1, line)
            self.skip_effects = False
        self.pager(title, lines)

    def _confirm_rects(self):
        gap = self.cw
        h = int(self.lh * 2.4)
        w = (self.W - 3 * gap) // 2
        y = self.H - h - 2 * gap
        return pygame.Rect(gap, y, w, h), pygame.Rect(2 * gap + w, y, w, h)

    def confirm(self, title: str, question: str) -> bool:
        while True:
            self.frame(title, "y yes   n no")
            for i, line in enumerate(wrap_lines([question], (self.W - 2 * self.cw) // self.cw)):
                self.text(line, self.cw, self.body_top + i * self.lh, BRIGHT)
            yes, no = self._confirm_rects()
            self.button(yes, "YES", active=True)
            self.button(no, "NO")
            self.refresh()
            ev = self.wait_event()
            if ev[0] == "key":
                if ev[1] == pygame.K_y:
                    return True
                if ev[1] == pygame.K_n or ev[1] in BACK:
                    return False
            elif ev[0] == "tap":
                if yes.collidepoint(ev[1]):
                    return True
                if no.collidepoint(ev[1]) or self._hit_back(ev):
                    return False

    def busy(self, title: str, text: str) -> None:
        self.frame(title, back=False)
        self.text(self.fit(text, self.W - self.cw), self.cw, self.body_top, BRIGHT)
        self.refresh()
        pygame.event.pump()

    def status(self, title: str, lines: list[str], button: str = "") -> None:
        self.frame(title, f"any key: {button.lower()}" if button else "", back=False)
        for i, line in enumerate(lines):
            self.text(self.fit(line, self.W - self.cw), self.cw, self.body_top + i * self.lh,
                      BRIGHT if i == 0 else NORMAL)
        if button and self.touch:
            self.button(self._footer_rects(1)[0], button, active=True)
        self.refresh()

    def poll_stop(self, seconds: float) -> bool:
        ev = self.wait_event(seconds)
        return bool(ev) and ev[0] in ("key", "tap")

    def prompt(self, title: str, label: str, initial: str = "", max_len: int = 2000):
        buf = list(initial)
        layer = "abc"
        while True:
            self.frame(title, "ENTER done   ESC cancel")
            self.text(self.fit(label, self.W - self.cw), self.cw, self.body_top, BRIGHT)
            keys = self._keyboard_layout(layer) if self.touch else []
            box_top = self.body_top + int(self.lh * 1.3)
            box_bottom = (keys[0][0].top - self.lh // 2) if keys else self.H - self.lh * 2
            box = pygame.Rect(self.cw // 2, box_top, self.W - self.cw, max(self.lh + 8, box_bottom - box_top))
            pygame.draw.rect(self.canvas, self.c["edge"], box, 2, border_radius=max(3, self.lh // 5))
            cols = max(1, (box.w - self.cw) // self.cw)
            shown = "".join(buf) + "█"
            lines = [shown[i:i + cols] for i in range(0, len(shown), cols)]
            fit_rows = max(1, (box.h - 8) // self.lh)
            for i, line in enumerate(lines[-fit_rows:]):
                self.text(line, box.x + self.cw // 2, box.y + 4 + i * self.lh)
            for rect, action, key_label in keys:
                self.button(rect, key_label, active=action[0] == "ok")
            self.refresh()

            ev = self.wait_event()
            if ev[0] == "key":
                key, ch = ev[1], ev[2]
                if key in ENTER:
                    return "".join(buf).strip()
                if key == pygame.K_ESCAPE:
                    return None
                if key == pygame.K_BACKSPACE:
                    if buf:
                        buf.pop()
                elif ch == "\x15":  # Ctrl+U
                    buf.clear()
                elif ch and ch.isprintable() and len(buf) < max_len:
                    buf.append(ch)
            elif ev[0] == "tap":
                if self._hit_back(ev):
                    return None
                for rect, action, _ in keys:
                    if not rect.collidepoint(ev[1]):
                        continue
                    kind = action[0]
                    if kind == "char" and len(buf) < max_len:
                        buf.append(action[1])
                        if layer == "ABC":
                            layer = "abc"  # shift is one-shot, like a phone
                    elif kind == "space" and len(buf) < max_len:
                        buf.append(" ")
                    elif kind == "del" and buf:
                        buf.pop()
                    elif kind == "shift":
                        layer = "ABC" if layer == "abc" else "abc"
                    elif kind == "sym":
                        layer = "abc" if layer == "sym" else "sym"
                    elif kind == "ok":
                        return "".join(buf).strip()
                    break
