"""Graphics mode: Uplink-9 drawn straight onto the device's display with pygame, with touch.

On the device's own console there's no desktop: SDL draws through KMS/DRM. On a desktop (or Windows)
it opens a window, and mouse clicks count as taps.

Touch controls, added around the same screens the text mode shows:
  tap an option          pick it
  tap elsewhere          ENTER (pause a tape, skip the boot, ...)
  swipe up / down        scroll
  buttons at the bottom  made from the screen's footer: [ESC] BACK, [ENTER] PAUSE, [▲▼] ...
  on-screen keyboard     whenever a screen wants typing
A physical keyboard works alongside all of it.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from .engine import BG, Opt  # noqa: E402

FONT_NAMES = ["dejavusansmono", "liberationmono", "notomono", "ubuntumono", "consolas", "couriernew"]
CONSOLE_DRIVERS = {"kmsdrm", "fbcon", "directfb"}
DRAG_START_PX = 14
TEXT_SCALE = {"AUTO": 1.0, "SMALL": 0.82, "LARGE": 1.22}

KEYBOARD = {
    "abc": ["1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm,./"],
    "ABC": ["1234567890", "QWERTYUIOP", "ASDFGHJKL_", "ZXCVBNM?!:"],
    "sym": ["!@#$%^&*()", "-_=+[]{}\\|", ":;\"'<>?~`'", "/.,@&€£$%#"],
}

KEYNAMES = {
    pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
    pygame.K_RETURN: "enter", pygame.K_KP_ENTER: "enter", pygame.K_ESCAPE: "escape",
    pygame.K_BACKSPACE: "backspace", pygame.K_PAGEUP: "pageup", pygame.K_PAGEDOWN: "pagedown",
    pygame.K_HOME: "home", pygame.K_END: "end", pygame.K_TAB: "tab", pygame.K_DELETE: "delete",
}

FOOTER_TOKEN = re.compile(r"\[([^\]]+)\]\s*([^\[]*)")


class DisplayUnavailable(Exception):
    pass


def hex_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def footer_buttons(view, typing: bool) -> list[tuple[str, str]]:
    """Touch buttons for a screen, read from its footer hints. [(label, key)]."""
    if view is None:
        return []
    out: list[tuple[str, str]] = []
    has_back = False
    for part in view.footer:
        for key, label in FOOTER_TOKEN.findall(part or ""):
            key, label = key.strip().upper(), label.strip().upper()
            if key == "ESC":
                if not view.locked:
                    out.append((label or "BACK", "escape"))
                    has_back = True
            elif key == "ENTER":
                if label != "SELECT" and not typing:   # options are tapped; typing has its own key
                    out.append((label or "OK", "enter"))
            elif key == "▲▼":
                out += [("▲", "up"), ("▼", "down")]
            elif key == "◄►":
                out += [("◄", "left"), ("► " + label if label else "►", "right")]
            elif key == "SPACE":
                out.append((label or "SPACE", "space"))
            elif len(key) == 1 and key.isalnum():
                out.append((f"{key} {label}".strip(), key.lower()))
    if not has_back and view.back is None and not view.locked:
        out.append(("BACK", "escape"))
    return out


def enter_label(view) -> str:
    for part in view.footer:
        for key, label in FOOTER_TOKEN.findall(part or ""):
            if key.strip().upper() == "ENTER" and label.strip():
                return label.strip().upper()
    return "OK"


class _Timer:
    def __init__(self, interval: float, fn, repeat: bool):
        self.interval, self.fn, self.repeat = interval, fn, repeat
        self.due = time.monotonic() + interval
        self.active = True

    def stop(self) -> None:
        self.active = False


class TouchHost:
    """Runs the engine on a pygame display. Pairs with EngineCore (see make_touch_app)."""

    interface = "GRAPHICS"

    def __init__(self):
        self.touch = False
        self.touch_setting = "AUTO"       # AUTO: the first touch switches touch mode on
        self.window = (720, 720)          # HackberryPi-shaped window on a desktop
        self.fullscreen_pref = "AUTO"
        self.display = None
        self.driver = ""
        self._timers: list[_Timer] = []
        self._calls: "queue.Queue" = queue.Queue()
        self._main_thread = threading.main_thread()
        self._done = False
        self._result = None
        self._code = 0
        self._press = None
        self._dragging = False
        self._last_y = 0
        self._drag_acc = 0.0
        self._layer = "abc"
        self._buttons: list = []          # [(rect, label, key)]
        self._keys: list = []             # [(rect, label, action)]
        self._grid = pygame.Rect(0, 0, 0, 0)
        self._painted = False

    # ------------------------------------------------------------------ display
    def open_display(self) -> None:
        try:
            pygame.display.init()
            pygame.font.init()
        except pygame.error as e:
            raise DisplayUnavailable(str(e)) from e
        self.driver = pygame.display.get_driver()
        want = self.fullscreen_pref
        full = self.driver in CONSOLE_DRIVERS if want == "AUTO" else want == "ON"
        try:
            if full:
                self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                pygame.mouse.set_visible(False)
            else:
                self.display = pygame.display.set_mode(self.window, pygame.RESIZABLE)
        except pygame.error as e:
            pygame.quit()
            raise DisplayUnavailable(str(e)) from e
        pygame.display.set_caption("UPLINK-9")
        pygame.key.set_repeat(400, 40)
        self._fonts()

    def _fonts(self) -> None:
        W, H = self.display.get_size()
        scale = TEXT_SCALE.get(self.cfg.get("text_size", "AUTO"), 1.0) if hasattr(self, "cfg") else 1.0
        # aim for about 44 columns with touch (bigger targets), about 66 with a keyboard only
        size = min(H / 23, W / 27.5) if self.touch else min(H / 32, W / 40)
        size = max(12, min(int(size * scale), 72))
        path = next((p for p in (pygame.font.match_font(n) for n in FONT_NAMES) if p), None)
        self.font = pygame.font.Font(path, size)
        self.font_bold = pygame.font.Font(path, size)
        self.font_bold.set_bold(True)
        self.cw = max(1, self.font.size("M")[0])
        self.lh = max(1, self.font.get_linesize())
        self.mono = self.font.size("i")[0] == self.cw and self.font.size("█")[0] == self.cw
        self.pitch = int(self.lh * (1.3 if self.touch else 1.05))   # row spacing: room for fingers
        self.cell_ratio = self.pitch / self.cw
        self.scan = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(0, H, 3):
            pygame.draw.line(self.scan, (0, 0, 0, 70), (0, y), (W, y))

    def set_touch(self, on: bool) -> None:
        if on != self.touch:
            self.touch = on
            if self.display is not None:
                self._fonts()
                self.repaint()

    def describe_screen(self) -> str:
        if self.display is None:
            return "NONE"
        W, H = self.display.get_size()
        return f"{W}x{H} {'TOUCH' if self.touch else 'KEYS'}"

    # ------------------------------------------------------------------ layout
    def _layout(self) -> None:
        """Place the touch controls for the current view; the text grid gets the rest."""
        W, H = self.display.get_size()
        gap = max(4, self.cw // 2)
        bottom = H
        self._buttons, self._keys = [], []
        view = getattr(self, "view", None)
        typing = bool(view and view.typing and view.on_char)   # boot shows a cursor but takes no typing
        if self.touch and typing:
            kb_top = int(H * 0.52)
            self._keys = self._keyboard(kb_top, W, H, gap, enter_label(view))
            bottom = kb_top - gap
        if self.touch:
            buttons = footer_buttons(view, typing)
            if buttons:
                bh = int(self.lh * 1.8)
                y = bottom - bh - gap
                w = (W - gap * (len(buttons) + 1)) / len(buttons)
                for i, (label, key) in enumerate(buttons):
                    self._buttons.append((pygame.Rect(int(gap + i * (w + gap)), y, int(w), bh), label, key))
                bottom = y - gap
        top = self.lh // 2
        self._grid = pygame.Rect(self.cw, top, W - 2 * self.cw, max(self.pitch * 5, bottom - top))

    def _keyboard(self, top: int, W: int, H: int, gap: int, ok_label: str) -> list:
        rows = KEYBOARD[self._layer]
        kh = (H - top - gap * 6) // 5
        keys = []
        for r, row in enumerate(rows):
            kw = (W - gap * (len(row) + 1)) / len(row)
            y = top + r * (kh + gap)
            for i, ch in enumerate(row):
                keys.append((pygame.Rect(int(gap + i * (kw + gap)), y, int(kw), kh), ch, ("char", ch)))
        specials = [("shift", "aA" if self._layer == "ABC" else "Aa", 1.3),
                    ("sym", "abc" if self._layer == "sym" else "#+=", 1.3),
                    ("space", "SPACE", 3.4), ("del", "DEL", 1.4), ("ok", ok_label[:9], 1.8)]
        total = W - gap * (len(specials) + 1)
        weight = sum(s[2] for s in specials)
        x, y = gap, top + 4 * (kh + gap)
        for action, label, wt in specials:
            w = int(total * wt / weight)
            keys.append((pygame.Rect(int(x), y, w, kh), label, (action,)))
            x += w + gap
        return keys

    def screen_size(self):
        if self.display is None:
            return None
        self._layout()
        return max(10, self._grid.w // self.cw), max(5, self._grid.h // self.pitch)

    # ------------------------------------------------------------------ drawing
    def _text(self, text: str, x: int, y: int, color, bold: bool = False) -> None:
        if not text:
            return
        font = self.font_bold if bold else self.font
        if self.mono:
            self.display.blit(font.render(text, True, color), (x, y))
        else:   # no monospace font found: place each character on the grid
            for i, ch in enumerate(text):
                if ch != " ":
                    self.display.blit(font.render(ch, True, color), (x + i * self.cw, y))

    def _button(self, rect, label: str, active: bool = False) -> None:
        phos = hex_rgb(self.pal[0])
        dim = hex_rgb(self.pal[1])
        bg = hex_rgb(BG)
        radius = max(3, self.lh // 5)
        if active:
            pygame.draw.rect(self.display, phos, rect, border_radius=radius)
        else:
            pygame.draw.rect(self.display, dim, rect, 2, border_radius=radius)
        max_chars = max(1, (rect.w - 6) // self.cw)
        label = label if len(label) <= max_chars else label[:max_chars]
        tw = len(label) * self.cw if self.mono else self.font.size(label)[0]
        self._text(label, rect.x + (rect.w - tw) // 2, rect.y + (rect.h - self.lh) // 2, bg if active else phos)

    def paint(self, rows, pad_left: int, pad_top: int) -> None:
        if self.display is None:
            return
        self.display.fill(hex_rgb(BG))
        g = self._grid
        x0 = g.x + pad_left * self.cw
        off = (self.pitch - self.lh) // 2
        for i, r in enumerate(rows):
            y = g.y + (pad_top + i) * self.pitch
            if r.bg:
                pygame.draw.rect(self.display, hex_rgb(r.bg), (x0 - self.cw // 3, y, len(r.text) * self.cw + self.cw // 3 * 2, self.pitch))
            self._text(r.text.rstrip(), x0, y + off, hex_rgb(r.fg), r.bold)
        for rect, label, key in self._buttons:
            self._button(rect, label, active=key == "enter")
        for rect, label, action in self._keys:
            self._button(rect, label, active=action[0] == "ok")
        if not self.plain and self.cfg.get("scanlines", "ON") == "ON":
            self.display.blit(self.scan, (0, 0))
        pygame.display.flip()
        self._painted = True

    # ------------------------------------------------------------------ host services
    def set_interval(self, seconds: float, fn):
        t = _Timer(seconds, fn, True)
        self._timers.append(t)
        return t

    def set_timer(self, seconds: float, fn):
        t = _Timer(seconds, fn, False)
        self._timers.append(t)
        return t

    def call_from_thread(self, fn, *args):
        if threading.current_thread() is self._main_thread:
            return fn(*args)
        if self._done:
            raise RuntimeError("terminal is closing")
        fut: Future = Future()
        self._calls.put((fn, args, fut))
        try:
            pygame.event.post(pygame.event.Event(pygame.USEREVENT))
        except pygame.error:
            pass
        try:
            return fut.result(timeout=30)
        except TimeoutError as e:
            raise RuntimeError("terminal did not answer") from e

    def run_worker(self, fn, thread: bool = True, exclusive: bool = False):
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        return t

    def exit(self, result=None, return_code: int = 0) -> None:
        self._result = result
        self._code = return_code
        self._done = True

    @property
    def return_code(self) -> int:
        return self._code

    @contextmanager
    def suspend(self):
        """Give the console to another program (ssh), then take the screen back."""
        pygame.display.quit()
        self.display = None
        try:
            yield
        finally:
            self.open_display()
            self.repaint()

    # ------------------------------------------------------------------ input
    def _key(self, ev) -> None:
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL
        if ctrl and ev.key in (pygame.K_q, pygame.K_c):
            self.request_quit()
            return
        if ctrl and ev.key == pygame.K_u:
            self.press("ctrl+u")
            return
        name = KEYNAMES.get(ev.key)
        if name:
            self.press(name)
            return
        ch = getattr(ev, "unicode", "")
        if ev.key == pygame.K_SPACE:
            self.press("space", " ", True)
        elif ch and ch.isprintable():
            self.press(ch, ch, True)

    def _tap(self, pos) -> None:
        for rect, label, key in self._buttons:
            if rect.collidepoint(pos):
                self.press(key, " " if key == "space" else None, key == "space")
                return
        for rect, label, action in self._keys:
            if rect.collidepoint(pos):
                self._keyboard_press(action)
                return
        if self._grid.collidepoint(pos):
            self.tap_row((pos[1] - self._grid.y) // self.pitch)

    def _keyboard_press(self, action) -> None:
        kind = action[0]
        if kind == "char":
            self.press(action[1], action[1], True)
            if self._layer == "ABC":
                self._layer = "abc"            # shift is one-shot, like a phone
                self.repaint()
        elif kind == "space":
            self.press("space", " ", True)
        elif kind == "del":
            self.press("backspace")
        elif kind == "ok":
            self.press("enter")
        elif kind == "shift":
            self._layer = "ABC" if self._layer == "abc" else "abc"
            self.repaint()
        elif kind == "sym":
            self._layer = "abc" if self._layer == "sym" else "sym"
            self.repaint()

    def _scroll(self, steps: int) -> None:
        key = "down" if steps > 0 else "up"
        for _ in range(abs(steps)):
            self.press(key)

    def handle_event(self, ev) -> None:
        T = pygame
        if ev.type == T.QUIT:
            self.exit()          # window closed, or SIGTERM at shutdown (SDL turns it into QUIT)
        elif ev.type == T.KEYDOWN:
            self._key(ev)
        elif ev.type in (T.FINGERDOWN, T.FINGERUP, T.FINGERMOTION):
            if self.touch_setting == "AUTO":
                self.set_touch(True)            # detection missed it: the first touch turns touch mode on
        elif ev.type == T.MOUSEBUTTONDOWN and ev.button == 1:
            if getattr(ev, "touch", False) and self.touch_setting == "AUTO":
                self.set_touch(True)
            self._press, self._last_y, self._dragging, self._drag_acc = ev.pos, ev.pos[1], False, 0.0
        elif ev.type == T.MOUSEMOTION and self._press:
            if not self._dragging and abs(ev.pos[1] - self._press[1]) > DRAG_START_PX:
                self._dragging = True
            if self._dragging:
                self._drag_acc += ev.pos[1] - self._last_y
                self._last_y = ev.pos[1]
                steps = int(self._drag_acc / self.pitch)
                if steps:
                    self._drag_acc -= steps * self.pitch
                    self._scroll(-steps)        # finger up = content up = further down the list
        elif ev.type == T.MOUSEBUTTONUP and ev.button == 1 and self._press:
            pos, dragged = self._press, self._dragging
            self._press, self._dragging = None, False
            if not dragged:
                self._tap(pos)
        elif ev.type == T.MOUSEWHEEL:
            self._scroll(-ev.y)
        elif ev.type in (T.VIDEORESIZE, T.WINDOWSIZECHANGED):
            self.display = pygame.display.get_surface()
            self._fonts()
            self.repaint()
        elif ev.type in (T.WINDOWEXPOSED, T.VIDEOEXPOSE):
            self.repaint()

    # ------------------------------------------------------------------ main loop
    def pump(self, timeout: float = 0.0) -> None:
        """One round of the loop: wait up to `timeout` for input, then run calls and due timers."""
        if timeout > 0:
            ev = pygame.event.wait(max(1, int(timeout * 1000)))
            events = [ev] + pygame.event.get()
        else:
            events = pygame.event.get()
        for ev in events:
            if ev.type != pygame.NOEVENT:
                try:
                    self.handle_event(ev)
                except Exception as e:  # keep the terminal alive
                    self.fail(e)
        while True:
            try:
                fn, args, fut = self._calls.get_nowait()
            except queue.Empty:
                break
            try:
                fut.set_result(fn(*args))
            except Exception as e:
                fut.set_exception(e)
        now = time.monotonic()
        for t in list(self._timers):
            if not t.active:
                continue
            if t.due <= now:
                if t.repeat:
                    t.due = max(t.due + t.interval, now + t.interval / 4)
                else:
                    t.active = False
                try:
                    t.fn()
                except Exception as e:
                    self.fail(e)
        self._timers = [t for t in self._timers if t.active]

    def _next_wait(self) -> float:
        if not self._calls.empty():
            return 0.0
        due = [t.due for t in self._timers if t.active]
        if not due:
            return 0.5
        return max(0.0, min(min(due) - time.monotonic(), 0.5))

    def run(self):
        self.open_display()
        self.core_start()
        try:
            while not self._done:
                self.pump(self._next_wait())
        finally:
            self._done = True
            while not self._calls.empty():        # don't leave background threads waiting
                try:
                    _, _, fut = self._calls.get_nowait()
                    fut.set_exception(RuntimeError("terminal closed"))
                except queue.Empty:
                    break
            try:
                self.core_stop()
            finally:
                pygame.quit()
        return self._result


def make_touch_app(after_update: bool = False, no_boot: bool = False, touch: bool = False,
                   touch_setting: str = "AUTO"):
    """The Uplink-9 app on a pygame display."""
    from .app import UplinkCore

    class UplinkTouch(UplinkCore, TouchHost):
        def __init__(self):
            super().__init__(after_update=after_update, no_boot=no_boot)
            self.touch = touch
            self.touch_setting = touch_setting
            self.fullscreen_pref = self.cfg.get("fullscreen", "AUTO")

    return UplinkTouch()


__all__ = ["DisplayUnavailable", "TouchHost", "footer_buttons", "make_touch_app", "Opt"]
