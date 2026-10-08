"""The terminal engine: draws a view (title, lines, options, log, input) and routes keys.

Every screen is a function that returns a View. The engine rebuilds the view with redraw()
when state changes, and re-renders the cached view on timer ticks (clock, cursor blink).

EngineCore holds all of that and knows nothing about the screen. A host puts it on a screen:
  Engine (below)      text mode through Textual: terminals, SSH, Windows
  gui.TouchHost       graphics through pygame: the device's own display, with touch
A host provides set_interval, set_timer, call_from_thread, run_worker, exit, suspend,
screen_size() and paint(rows, pad_left, pad_top), and feeds keys to press() and taps to tap_row().
"""
from __future__ import annotations

import os
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import sound
from .storage import DATA_DIR, Config

# The Linux console font lacks a few symbols; swap them for ASCII there.
CONSOLE = os.environ.get("TERM") == "linux"
CONSOLE_GLYPHS = str.maketrans({"●": "*", "•": "*", "♪": "~", "▲": "^", "▼": "v", "·": "-", "→": ">",
                                "◄": "<", "►": ">", "▁": "_", "▂": ".", "▃": ":", "▅": "=", "▆": "+", "▇": "#"})
CRASH_LOG = DATA_DIR / "crash.log"

PALETTES = {
    "GREEN": ("#3dff7a", "#1f8a45"),
    "AMBER": ("#ffb642", "#9a6a1c"),
    "WHITE": ("#e8f1ff", "#7d8796"),
    "BLUE": ("#5ad2ff", "#2a7590"),
}
WARN = "#ffb642"
BAD = "#ff5a4a"
BG = "#000000"


@dataclass
class Row:
    """One finished screen row: what a host draws."""
    text: str
    fg: str
    bg: str = ""
    bold: bool = False


@dataclass
class Line:
    text: str
    style: str = ""          # "", "dim", "warn", "bad"


@dataclass
class Opt:
    label: str
    go: Optional[Callable] = None
    tag: str = ""
    style: str = ""
    raw: bool = False        # keep the label's case (file names, URLs)


@dataclass
class Log:
    lines: list              # list[Line], shown in the space left over
    top: bool = False        # True: text flows from the top (tapes, editor); False: bottom-anchored (chat)


@dataclass
class Input:
    prompt: str
    buf: str
    mask: bool = False       # passwords: show * instead of the letters


ASPECTS = {"FILL": None, "1:1": 1.0, "4:3": 4 / 3, "16:10": 16 / 10, "16:9": 16 / 9}
CELL_RATIO = 2.0             # a terminal cell is about twice as tall as it is wide


@dataclass
class View:
    id: str
    title: str
    items: list = field(default_factory=list)
    footer: tuple = ("", "[ESC] BACK")
    back: Optional[Callable] = None       # what ESC does (default: main menu)
    on_enter: Optional[Callable] = None   # replaces "activate option" for non-menu views
    on_key: Optional[Callable] = None     # custom keys; return True when handled
    on_char: Optional[Callable] = None    # typing views
    on_backspace: Optional[Callable] = None
    locked: bool = False                  # ESC disabled (firmware flashing)

    @property
    def opts(self):
        return [i for i in self.items if isinstance(i, Opt)]

    @property
    def typing(self):
        return any(isinstance(i, Input) for i in self.items)


class EngineCore:
    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.view: Optional[View] = None
        self.view_fn: Optional[Callable] = None
        self.sel = 0
        self.scroll = 0
        self.body_h = 20
        self.blink_on = True
        self.toast_text = ""
        self.toast_until = 0.0
        self.row_map: dict[int, int] = {}
        self._ul_timers = []
        self._ul_sig = None
        self.role = "ADMIN"          # USER or ADMIN; set by the login screen
        self.pad_top = 0
        self.force_plain = False     # uplink --plain: plain mode for this session only
        self.cell_ratio = CELL_RATIO # height / width of one character cell on this screen

    # ------------------------------------------------------------ settings helpers
    @property
    def plain(self) -> bool:
        return self.force_plain or self.cfg["plain"] == "ON"

    def fx(self, key: str) -> bool:
        """An effect setting, forced off in plain (realism) mode."""
        return not self.plain and self.cfg[key] == "ON"

    def sfx(self, name: str) -> None:
        if self.fx("sounds"):
            sound.play(name)

    @property
    def pal(self):
        return PALETTES["GREEN"] if self.plain else PALETTES.get(self.cfg["color"], PALETTES["GREEN"])

    def style_for(self, s: str) -> str:
        phos, dim = self.pal
        if self.plain:
            return dim if s == "dim" else phos
        return {"dim": dim, "warn": WARN, "bad": BAD}.get(s, phos)

    # ------------------------------------------------------------ lifecycle (called by the host)
    def core_start(self) -> None:
        self.set_interval(0.5, self._tick)

    def core_stop(self) -> None:
        pass

    def _tick(self) -> None:
        self.blink_on = not self.blink_on if self.fx("cursor_blink") else True
        self.render_view()

    # ------------------------------------------------------------ navigation
    # ------------------------------------------------------------ crash protection
    def guard(self, fn: Callable) -> Callable:
        """Wrap a callback so an error shows an error screen instead of closing the terminal."""
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                self.fail(e)
        return wrapped

    def fail(self, e: Exception) -> None:
        try:
            CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ===\n"))
                f.write("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        except OSError:
            pass
        self.stop_timers()
        self.sfx("buzz")
        msg = f"{type(e).__name__}: {e}"[:200]
        self.view_fn = lambda: View("error", "SYSTEM // ERROR", [
            Line("SOMETHING WENT WRONG. THE TERMINAL IS STILL RUNNING.", "warn"), Line(""),
            Line(msg, "dim"), Line(""), Line("DETAILS SAVED TO " + str(CRASH_LOG), "dim"), Line(""),
            Opt("MAIN MENU", lambda: self.show(self.main)),
        ], back=lambda: self.show(self.main))
        self.sel = 0
        self.view = self.view_fn()
        self.render_view()

    # Ctrl+Q / Ctrl+C would drop to the shell; only an admin may do that
    def request_quit(self) -> None:
        if self.role == "ADMIN":
            self.exit()
        else:
            self.toast("LOCKED: ONLY AN ADMIN CAN EXIT")

    def ui(self, fn: Callable, *args) -> None:
        """Run fn on the UI thread from a background thread. Safe while the app is shutting down."""
        try:
            self.call_from_thread(self.guard(fn), *args)
        except RuntimeError:
            pass

    def every(self, seconds: float, fn: Callable):
        """A timer that belongs to the current screen and stops when the screen changes."""
        t = self.set_interval(seconds, self.guard(fn))
        self._ul_timers.append(t)
        return t

    def later(self, seconds: float, fn: Callable):
        t = self.set_timer(seconds, self.guard(fn))
        self._ul_timers.append(t)
        return t

    def stop_timers(self) -> None:
        for t in self._ul_timers:
            t.stop()
        self._ul_timers = []

    def show(self, fn: Callable, keep_sel: bool = False) -> None:
        self.stop_timers()
        if not keep_sel:
            self.sel = 0
            self.scroll = 0
        self.view_fn = fn
        self.redraw()

    def redraw(self) -> None:
        if not self.view_fn:
            return
        try:
            self.view = self.view_fn()
        except Exception as e:
            self.fail(e)
            return
        n = len(self.view.opts)
        self.sel = max(0, min(self.sel, n - 1)) if n else 0
        self.render_view()

    def toast(self, text: str, seconds: float = 4) -> None:
        self.toast_text = text
        self.toast_until = time.monotonic() + seconds
        self.render_view()

    def bg(self, work: Callable, done: Optional[Callable] = None) -> None:
        """Run work() in a thread, then done(result) back on the UI thread."""
        def runner():
            try:
                result = work()
            except Exception as e:  # keep the terminal alive whatever happens
                result = e
            if done:
                self.ui(done, result)
        self.run_worker(runner, thread=True, exclusive=False)

    # ------------------------------------------------------------ rendering
    def _lr(self, left: str, right: str, width: int, fg: str) -> Row:
        left = left[: max(0, width - len(right) - 1)]
        return Row(left + " " * max(1, width - len(left) - len(right)) + right, fg)

    def _wrap(self, text: str, width: int) -> list[str]:
        out = []
        for para in (text.split("\n") if text else [""]):
            out += textwrap.wrap(para, width, replace_whitespace=False, drop_whitespace=False) or [""]
        return out

    def render_view(self) -> None:
        size = self.screen_size() if self.view else None
        if not size:
            return
        W, H = size
        if W < 10 or H < 5:
            return
        full_w, full_h = W, H
        ratio = ASPECTS.get(self.cfg.get("aspect", "FILL"))
        if ratio:
            cr = self.cell_ratio
            if W / (H * cr) > ratio:
                W = max(20, round(H * cr * ratio))
            else:
                H = max(8, round(W / (cr * ratio)))
        pad_left = (full_w - W) // 2
        self.pad_top = (full_h - H) // 2
        v = self.view
        phos, dim = self.pal
        bright = self.style_for("")
        head = [self._lr(v.title.upper(), self.clock(), W, bright)]
        if not self.plain:
            head.append(Row("─" * W, dim))
        foot = []
        if not self.plain:
            foot.append(Row("─" * W, dim))
        foot.append(self._lr(v.footer[0], v.footer[1], W, dim))
        toast = []
        if self.toast_text and time.monotonic() < self.toast_until:
            toast.append(Row(self.toast_text[:W].upper(), self.style_for("warn")))
        body_h = max(1, H - len(head) - len(foot) - len(toast))
        self.body_h = body_h

        # flatten body into rows: (Text, option index or None)
        fixed: list = []
        log_at = None
        opt_i = 0
        for item in v.items:
            if isinstance(item, Line):
                for r in self._wrap(item.text, W):
                    fixed.append((Row(r, self.style_for(item.style)), None))
            elif isinstance(item, Opt):
                fixed.append((self._opt_row(item, opt_i, W), opt_i))
                opt_i += 1
            elif isinstance(item, Input):
                cur = ("█" if self.blink_on else " ")
                shown_buf = "*" * len(item.buf) if item.mask else item.buf
                rows = self._wrap(item.prompt + shown_buf + cur, W)
                for r in rows:
                    fixed.append((Row(r, bright), None))
            elif isinstance(item, Log):
                log_at = len(fixed)
                fixed.append(("LOG", None))
        rows = fixed
        if log_at is not None:
            log_item = next(i for i in v.items if isinstance(i, Log))
            space = max(0, body_h - (len(fixed) - 1))
            lrows = []
            for ln in log_item.lines:
                for r in self._wrap(ln.text, W):
                    lrows.append((Row(r, self.style_for(ln.style)), None))
            lrows = lrows[-space:] if space else []
            pad = [(Row("", phos), None)] * (space - len(lrows))
            middle = (lrows + pad) if log_item.top else (pad + lrows)
            rows = fixed[:log_at] + middle + fixed[log_at + 1:]

        # keep the selected option on screen
        if len(rows) > body_h:
            sel_row = next((i for i, (_, o) in enumerate(rows) if o == self.sel), 0)
            if sel_row < self.scroll:
                self.scroll = sel_row
            elif sel_row >= self.scroll + body_h:
                self.scroll = sel_row - body_h + 1
            self.scroll = max(0, min(self.scroll, len(rows) - body_h))
        else:
            self.scroll = 0
        shown = rows[self.scroll: self.scroll + body_h]

        top = self.pad_top + len(head) + len(toast)
        self.row_map = {top + y: o for y, (_, o) in enumerate(shown) if o is not None}
        rows_out = head + toast + [r for r, _ in shown] + [Row("", phos)] * (body_h - len(shown)) + foot
        sig = (full_w, full_h, pad_left, self.pad_top, tuple((r.text, r.fg, r.bg, r.bold) for r in rows_out))
        if sig == self._ul_sig:
            return  # nothing changed: skip the screen write
        self._ul_sig = sig
        self.paint(rows_out, pad_left, self.pad_top)

    def repaint(self) -> None:
        """Draw again even if nothing changed (after the screen was lost or resized)."""
        self._ul_sig = None
        self.render_view()

    def _opt_row(self, o: Opt, i: int, W: int) -> Row:
        selected = i == self.sel
        col = self.style_for(o.style)
        label = (("> " if selected else "  ") if self.plain else "> ") + (o.label if o.raw else o.label.upper())
        tag = o.tag.upper()
        label = label[: max(1, W - len(tag) - 2)]
        text = label + " " * max(1, W - len(label) - len(tag)) + tag
        if self.plain:
            return Row(text, col, bold=selected)
        return Row(text, BG, col) if selected else Row(text, col)

    def clock(self) -> str:
        return time.strftime("%I:%M %p" if self.cfg["clock"] == "12H" else "%H:%M")

    # ------------------------------------------------------------ input
    def activate(self) -> None:
        opts = self.view.opts if self.view else []
        if 0 <= self.sel < len(opts) and opts[self.sel].go:
            self.sfx("blip")
            opts[self.sel].go()

    def move(self, d: int) -> None:
        n = len(self.view.opts) if self.view else 0
        if not n:
            return
        self.sel = (self.sel + d) % n if abs(d) == 1 else max(0, min(n - 1, self.sel + d))
        self.sfx("tick")
        self.render_view()

    def go_back(self) -> None:
        v = self.view
        if not v or v.locked:
            return
        if v.back:
            v.back()
        else:
            self.show(self.main)

    def press(self, key: str, ch=None, printable: bool = False) -> None:
        """A key from any host (keyboard, or a touch button standing in for one)."""
        if self.view is None:
            return
        if self.fx("key_clicks"):
            sound.play("click")
        try:
            self.handle_key(key, ch, printable)
        except Exception as e:
            self.fail(e)

    def handle_key(self, key: str, ch, printable: bool) -> None:
        v = self.view
        if v.typing:
            if key == "enter":
                v.on_enter and v.on_enter()
            elif key == "escape":
                self.go_back()
            elif key == "backspace":
                if v.on_backspace and v.on_backspace():
                    return
                self.go_back()
            elif key == "ctrl+u":                     # clear the whole line
                for _ in range(10000):
                    if not (v.on_backspace and v.on_backspace()):
                        break
            elif ch and printable and v.on_char:
                v.on_char(ch)
            return
        if v.on_key and v.on_key(key):
            return
        if key in ("up", "k", "w"):
            self.move(-1)
        elif key in ("down", "j", "s"):
            self.move(1)
        elif key in "123456789" and len(key) == 1 and v.opts:
            n = int(key) - 1                          # 1-9 jump straight to an option
            if n < len(v.opts):
                self.sel = n
                self.activate()
        elif key == "pageup":
            self.move(-(self.body_h - 1))
        elif key == "pagedown":
            self.move(self.body_h - 1)
        elif key in ("enter", "right", "space"):
            if v.on_enter:
                v.on_enter()
            else:
                self.activate()
        elif key in ("escape", "backspace", "left", "q"):
            self.go_back()

    def tap_row(self, row: int) -> None:
        """A click or tap on screen row `row`: pick the option there, or ENTER for screens without options."""
        try:
            o = self.row_map.get(row)
            if o is not None:
                self.sel = o
                self.activate()
            elif self.view and self.view.on_enter:
                self.view.on_enter()
        except Exception as e:
            self.fail(e)

    def main(self) -> View:  # overridden by the app
        return View("main", "MAIN")


# ====================================================================== text-mode host
class Engine(EngineCore):
    """Placeholder replaced below when Textual is installed (so the graphics mode works without it)."""


try:
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult
    from textual.widgets import Static
except ImportError:  # pragma: no cover - graphics-only install
    App = None

if App is not None:
    class TextualHost(App):
        """Runs the engine in a terminal through Textual."""
        CSS = f"""
        Screen {{ background: {BG}; }}
        #term {{ width: 100%; height: 100%; padding: 1 2; background: {BG}; }}
        """
        ENABLE_COMMAND_PALETTE = False
        interface = "TEXT"
        touch = False

        def compose(self) -> ComposeResult:
            yield Static(id="term")

        def on_mount(self) -> None:
            self.term = self.query_one("#term", Static)
            self.core_start()

        def on_unmount(self) -> None:
            self.core_stop()

        def on_resize(self, event: events.Resize) -> None:
            self.render_view()

        def screen_size(self):
            if not hasattr(self, "term"):
                return None
            return self.term.content_size.width, self.term.content_size.height

        def describe_screen(self) -> str:
            size = self.screen_size() or (0, 0)
            return f"TEXT {size[0]}x{size[1]}"

        def paint(self, rows, pad_left: int, pad_top: int) -> None:
            out = Text()
            for _ in range(pad_top):
                out.append("\n")
            margin = " " * pad_left
            for r in rows:
                text = r.text.translate(CONSOLE_GLYPHS) if CONSOLE else r.text
                style = ("bold " if r.bold else "") + r.fg + (f" on {r.bg}" if r.bg else "")
                out.append(margin)
                out.append(text, style=style)
                out.append("\n")
            out.rstrip()
            self.term.update(out)

        def on_key(self, event: events.Key) -> None:
            if self.view is None:
                return
            event.stop()
            event.prevent_default()
            self.press(event.key, event.character, event.is_printable)

        def on_click(self, event: events.Click) -> None:
            self.tap_row(event.y - 1)  # 1 = top padding

        def action_quit(self) -> None:
            self.request_quit()

        def action_help_quit(self) -> None:
            self.request_quit()

    class Engine(EngineCore, TextualHost):  # noqa: F811 - the real text-mode engine
        pass
