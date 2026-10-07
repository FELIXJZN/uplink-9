"""The terminal engine: draws a view (title, lines, options, log, input) and routes keys.

Every screen is a function that returns a View. The engine rebuilds the view with redraw()
when state changes, and re-renders the cached view on timer ticks (clock, cursor blink).
"""
from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Static

from . import sound
from .storage import Config

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


class Engine(App):
    CSS = f"""
    Screen {{ background: {BG}; }}
    #term {{ width: 100%; height: 100%; padding: 1 2; background: {BG}; }}
    """
    ENABLE_COMMAND_PALETTE = False

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

    # ------------------------------------------------------------ settings helpers
    @property
    def plain(self) -> bool:
        return self.cfg["plain"] == "ON"

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

    # ------------------------------------------------------------ lifecycle
    def compose(self) -> ComposeResult:
        yield Static(id="term")

    def on_mount(self) -> None:
        self.term = self.query_one("#term", Static)
        self.set_interval(0.5, self._tick)

    def on_resize(self, event: events.Resize) -> None:
        self.render_view()

    def _tick(self) -> None:
        self.blink_on = not self.blink_on if self.fx("cursor_blink") else True
        self.render_view()

    # ------------------------------------------------------------ navigation
    def every(self, seconds: float, fn: Callable):
        """A timer that belongs to the current screen and stops when the screen changes."""
        t = self.set_interval(seconds, fn)
        self._ul_timers.append(t)
        return t

    def later(self, seconds: float, fn: Callable):
        t = self.set_timer(seconds, fn)
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
        self.view = self.view_fn()
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
                self.call_from_thread(done, result)
        self.run_worker(runner, thread=True, exclusive=False)

    # ------------------------------------------------------------ rendering
    def _lr(self, left: str, right: str, width: int, style: str) -> Text:
        left = left[: max(0, width - len(right) - 1)]
        return Text(left + " " * max(1, width - len(left) - len(right)) + right, style=style)

    def _wrap(self, text: str, width: int) -> list[str]:
        out = []
        for para in (text.split("\n") if text else [""]):
            out += textwrap.wrap(para, width, replace_whitespace=False, drop_whitespace=False) or [""]
        return out

    def render_view(self) -> None:
        if not self.view or not hasattr(self, "term"):
            return
        W, H = self.term.content_size.width, self.term.content_size.height
        if W < 10 or H < 5:
            return
        v = self.view
        phos, dim = self.pal
        bright = self.style_for("")
        head = [self._lr(v.title.upper(), self.clock(), W, bright)]
        if not self.plain:
            head.append(Text("─" * W, style=dim))
        foot = []
        if not self.plain:
            foot.append(Text("─" * W, style=dim))
        foot.append(self._lr(v.footer[0], v.footer[1], W, dim))
        toast = []
        if self.toast_text and time.monotonic() < self.toast_until:
            toast.append(Text(self.toast_text[:W].upper(), style=self.style_for("warn")))
        body_h = max(1, H - len(head) - len(foot) - len(toast))
        self.body_h = body_h

        # flatten body into rows: (Text, option index or None)
        fixed: list = []
        log_at = None
        opt_i = 0
        for item in v.items:
            if isinstance(item, Line):
                for r in self._wrap(item.text, W):
                    fixed.append((Text(r, style=self.style_for(item.style)), None))
            elif isinstance(item, Opt):
                fixed.append((self._opt_row(item, opt_i, W), opt_i))
                opt_i += 1
            elif isinstance(item, Input):
                cur = ("█" if self.blink_on else " ")
                rows = self._wrap(item.prompt + item.buf + cur, W)
                for r in rows:
                    fixed.append((Text(r, style=bright), None))
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
                    lrows.append((Text(r, style=self.style_for(ln.style)), None))
            lrows = lrows[-space:] if space else []
            pad = [(Text(""), None)] * (space - len(lrows))
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

        top = len(head) + len(toast)
        self.row_map = {top + y: o for y, (_, o) in enumerate(shown) if o is not None}
        out = Text()
        for t in head + toast + [r for r, _ in shown] + [Text("")] * (body_h - len(shown)) + foot:
            out.append_text(t)
            out.append("\n")
        out.rstrip()
        self.term.update(out)

    def _opt_row(self, o: Opt, i: int, W: int) -> Text:
        selected = i == self.sel
        col = self.style_for(o.style)
        if self.plain:
            label = ("> " if selected else "  ") + (o.label if o.raw else o.label.upper())
            style = f"bold {col}" if selected else col
        else:
            label = "> " + (o.label if o.raw else o.label.upper())
            style = f"{BG} on {col}" if selected else col
        tag = o.tag.upper()
        label = label[: max(1, W - len(tag) - 2)]
        return Text(label + " " * max(1, W - len(label) - len(tag)) + tag, style=style)

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

    def on_key(self, event: events.Key) -> None:
        v = self.view
        if v is None:
            return
        key, ch = event.key, event.character
        if self.fx("key_clicks"):
            sound.play("click")
        event.stop()
        event.prevent_default()
        if v.typing:
            if key == "enter":
                v.on_enter and v.on_enter()
            elif key == "escape":
                self.go_back()
            elif key == "backspace":
                if v.on_backspace and v.on_backspace():
                    return
                self.go_back()
            elif ch and event.is_printable and v.on_char:
                v.on_char(ch)
            return
        if v.on_key and v.on_key(key):
            return
        if key in ("up", "k"):
            self.move(-1)
        elif key in ("down", "j"):
            self.move(1)
        elif key == "pageup":
            self.move(-(self.body_h - 1))
        elif key == "pagedown":
            self.move(self.body_h - 1)
        elif key in ("enter", "right", "space"):
            if v.on_enter:
                v.on_enter()
            else:
                self.activate()
        elif key in ("escape", "backspace", "left"):
            self.go_back()

    def on_click(self, event: events.Click) -> None:
        o = self.row_map.get(event.y - 1)  # 1 = top padding
        if o is not None:
            self.sel = o
            self.activate()
        elif self.view and self.view.on_enter:
            self.view.on_enter()

    def main(self) -> View:  # overridden by the app
        return View("main", "MAIN")
