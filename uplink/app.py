"""Uplink-9 screens. Each method that returns a View is one screen."""
from __future__ import annotations

import datetime
import getpass
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__, audio, sound, storage, system, updater, webhooks
from .engine import Engine, Input, Line, Log, Opt, View
from .tapes import BUILTIN_TAPES

SPEED = {"SLOW": 0.06, "NORMAL": 0.025, "FAST": 0.01, "INSTANT": 0}


def bar(p: float, w: int = 16) -> str:
    n = max(0, min(w, round(p / 100 * w)))
    return "█" * n + "░" * (w - n)


def ts(secs: float) -> str:
    s = int(secs)
    return f"{s // 60:02d}:{s % 60:02d}"


def dots(label: str, status: str, width: int = 36) -> str:
    return (f"> {label} ").ljust(width, ".") + f" {status}"


class Uplink(Engine):
    def __init__(self, after_update: bool = False):
        super().__init__()
        self.after_update = after_update
        self.drives: list[system.Drive] = []
        self.node_state: dict[str, dict] = {}
        self.vpn_info = None
        self.threads = storage.load_messages()
        self.user_tapes = storage.load_tapes()
        self.update_info = None
        self.mic_ok = None
        self._ul_stop = threading.Event()

    # ================================================================ startup
    def on_mount(self) -> None:
        super().on_mount()
        threading.Thread(target=sound.warm, daemon=True).start()
        self.show(self.boot_screen)
        self.bg(self.collect_boot_facts, self.start_boot_animation)

    def on_unmount(self) -> None:
        self._ul_stop.set()

    def collect_boot_facts(self):
        # run the slow checks side by side so a missing network can't stall the boot
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_info = pool.submit(system.sysinfo)
            f_drives = pool.submit(system.list_drives)
            f_ts = pool.submit(system.tailscale_status)
            f_mic = pool.submit(audio.can_record)
            info = dict(f_info.result())
            drives = f_drives.result()
            ts_state = f_ts.result()[0]
            self.mic_ok = f_mic.result()
        user = (os.environ.get("USER") or getpass.getuser() or "USER").upper()
        return [
            "4RDEN INDUSTRIES UNIFIED OPERATING SYSTEM",
            f"FIRMWARE V{__version__}" + (f" ({updater.commit()})" if updater.commit() else ""),
            "",
            dots("CORE " + info.get("MODEL", "?")[:18], "OK"),
            dots("MEMORY " + info.get("MEMORY", "?"), "OK"),
            dots("STORAGE " + info.get("STORAGE", "?"), "OK"),
            dots("USB DRIVES", str(len(drives))),
            dots("MICROPHONE", "OK" if self.mic_ok else "NONE"),
            dots("TAILNET", ts_state),
            "",
            f"WELCOME BACK, {user}.",
        ]

    def boot_screen(self) -> View:
        b = getattr(self, "_ul_boot", {"lines": [], "cur": ""})
        items = [Line(l) for l in b["lines"]]
        if b.get("cur") is not None:
            items.append(Input("", b.get("cur", "")))
        return View("boot", f"{self.cfg['device_name']} // BOOT", items, footer=("", "[ENTER] SKIP"),
                    on_enter=self.finish_boot, back=lambda: None)

    def start_boot_animation(self, lines) -> None:
        if getattr(self, "_ul_booted", False):
            return  # boot was skipped with ENTER before the checks finished
        if isinstance(lines, Exception):
            lines = ["4RDEN INDUSTRIES UNIFIED OPERATING SYSTEM", f"FIRMWARE V{__version__}", "", "BOOT CHECK FAILED: " + str(lines)]
        self.sfx("hum")
        self._ul_boot = {"lines": [], "cur": "", "todo": list(lines)}
        speed = 0 if (self.plain or not self.fx("animations")) else SPEED[self.cfg["text_speed"]]
        if not speed:
            self._ul_boot = {"lines": list(lines), "cur": None, "todo": []}
            self.redraw()
            self.later(0.8, self.finish_boot)
            return

        def step():
            b = self._ul_boot
            if getattr(self, "_ul_booted", False):
                self.stop_timers()
                return
            if not b["todo"]:
                b["cur"] = None
                self.redraw()
                self.stop_timers()
                self.later(0.9, self.finish_boot)
                return
            target = b["todo"][0]
            if len(b["cur"]) < len(target):
                b["cur"] = target[: len(b["cur"]) + 1]
                if len(b["cur"]) % 3 == 0:
                    self.sfx("click")
            else:
                b["lines"].append(target)
                b["todo"].pop(0)
                b["cur"] = ""
                if target.endswith(" OK"):
                    self.sfx("ok")
            self.redraw()
        self.every(speed, step)

    def finish_boot(self) -> None:
        if getattr(self, "_ul_booted", False):
            return
        self._ul_booted = True
        self.show(self.main)
        if self.after_update:
            self.toast(f"UPDATED TO V{__version__}")
        if storage.LOAD_PROBLEMS:
            problems = list(storage.LOAD_PROBLEMS)
            storage.LOAD_PROBLEMS.clear()
            self.sfx("buzz")
            self.message("SYSTEM // CHECK", ["SOME SAVED SETTINGS NEEDED FIXING:"] + [Line(p_, "dim") for p_ in problems],
                         lambda: self.show(self.main), "warn")
        self.hook("boot", f"booted, firmware v{__version__}")
        threading.Thread(target=self.usb_loop, daemon=True).start()
        threading.Thread(target=self.node_loop, daemon=True).start()
        threading.Thread(target=self.ntfy_loop, daemon=True).start()
        if self.cfg["update_check_boot"] == "ON" and updater.is_git():
            self.bg(lambda: updater.check(self.cfg["update_branch"]), self.boot_update_result)

    def boot_update_result(self, info) -> None:
        if isinstance(info, dict) and info.get("ok") and info.get("behind"):
            self.update_info = info
            self.sfx("chirp")
            self.toast(f"FIRMWARE V{info['version']} AVAILABLE: SETTINGS > UPDATE", 6)
            if self.view and self.view.id == "main":
                self.show(self.main, keep_sel=True)

    def hook(self, event: str, summary: str, data: dict | None = None, exclude: str = "") -> None:
        webhooks.fire(self.cfg["webhooks"], event, summary, data, self.cfg["device_name"], exclude,
                      on_done=lambda: self.ui(self.cfg.save))

    # ================================================================ main
    def main(self) -> View:
        up = sum(1 for n in self.cfg["nodes"] if self.node_state.get(n["name"], {}).get("up"))
        unread = sum(t.get("unread", 0) for t in self.threads)
        mounted = sum(1 for d in self.drives if d.mountpoint)
        fw_tag = f"V{self.update_info['version']} READY" if self.update_info else f"V{__version__}"
        return View("main", f"{self.cfg['device_name']} // MAIN", [
            Line("SELECT A FUNCTION:", "dim"),
            Opt("FILES", lambda: self.show(self.file_roots), "BROWSE"),
            Opt("USB DRIVES", lambda: self.show(self.usb), f"{len(self.drives)} FOUND" if self.drives else "NONE"),
            Opt("TRANSFER", lambda: self.show(self.file_roots), "PICK FILE"),
            Opt("MESSAGES", lambda: self.show(self.inbox), f"{unread} NEW" if unread else ""),
            Opt("NODES", lambda: self.show(self.nodes), f"{up}/{len(self.cfg['nodes'])} ON"),
            Opt("VPN", self.open_vpn, (self.vpn_info or {}).get("active", "")),
            Opt("HOLOTAPE", lambda: self.show(self.deck), f"{len(BUILTIN_TAPES) + len(self.user_tapes)} TAPES"),
            Opt("SETTINGS", lambda: self.show(self.settings), fw_tag, "warn" if self.update_info else ""),
            Opt("POWER", lambda: self.show(self.power)),
        ], footer=(f"USB:{mounted} MOUNTED" if self.drives else "", "[ENTER] SELECT"), back=lambda: None)

    # ================================================================ generic screens
    def message(self, title: str, lines: list, back, style: str = "") -> None:
        self.show(lambda: View("msg", title, [Line(l, style) if isinstance(l, str) else l for l in lines] +
                                 [Line(""), Opt("OK", back)], back=back))

    def confirm(self, title: str, question: str, detail: str, yes: str, on_yes, back, no: str = "NO, CANCEL") -> None:
        self.show(lambda: View("confirm", title, [
            Line(question, "warn"), Line(detail, "dim"), Line(""),
            Opt(no, back), Opt(yes, on_yes, style="warn"),
        ], back=back))

    def prompt(self, title: str, label: str, on_submit, back, initial: str = "", hint: str = "") -> None:
        st = {"buf": initial}

        def char(c):
            st["buf"] += c
            self.redraw()

        def backspace():
            if st["buf"]:
                st["buf"] = st["buf"][:-1]
                self.redraw()
                return True
            return False

        self.show(lambda: View("prompt", title, [
            Line(label, "dim"), *( [Line(hint, "dim")] if hint else [] ), Line(""), Input("> ", st["buf"]),
        ], footer=("[ENTER] OK", "[ESC] CANCEL"), back=back,
            on_enter=lambda: on_submit(st["buf"].strip()), on_char=char, on_backspace=backspace))

    def cycle(self, label: str, key: str, values: list, screen, note: str = "") -> Opt:
        def go():
            cur = self.cfg[key]
            self.cfg[key] = values[(values.index(cur) + 1) % len(values)] if cur in values else values[0]
            self.cfg.save()
            self.sfx("clack")
            self.show(screen, keep_sel=True)
        return Opt(label, go, note or self.cfg[key])

    # ================================================================ files
    def roots(self) -> list[tuple[str, Path]]:
        r = [("HOME", Path.home())]
        for d in self.drives:
            if d.mountpoint:
                r.append(("USB " + d.name, Path(d.mountpoint)))
        r.append(("SYSTEM /", Path(Path.home().anchor or "/")))
        return r

    def file_roots(self, mode: str = "browse") -> View:
        self.fb_mode = getattr(self, "fb_mode", "browse")
        dest = self.fb_mode != "browse"
        items = [Line("PICK A DESTINATION:" if dest else "LOCATIONS:", "dim")]
        for name, path in self.roots():
            items.append(Opt(name, lambda p=path: self.open_dir(p), str(path), raw=False))
        for d in self.drives:
            if not d.mountpoint:
                items.append(Opt("MOUNT USB " + d.name, lambda d=d: self.mount_then(d, self.open_dir), system.human(d.size), "warn"))
        return View("roots", "FILES // " + ("DESTINATION" if dest else "LOCATIONS"), items, back=self.leave_files)

    def leave_files(self) -> None:
        if getattr(self, "fb_mode", "browse") != "browse":
            src = self.fb_src
            self.fb_mode = "browse"
            self.show(lambda: self.file_menu(src))
        else:
            self.show(self.main)

    def open_dir(self, path: Path) -> None:
        self.fb_path = Path(path)
        self.show(self.browse)

    def browse(self) -> View:
        path = self.fb_path
        dest = getattr(self, "fb_mode", "browse") != "browse"
        items: list = [Line(str(path), "dim")]
        root_paths = [p for _, p in self.roots()]
        parent_ok = path not in root_paths and path.parent != path
        if parent_ok:
            items.append(Opt(".. UP", lambda: self.open_dir(path.parent), raw=False))
        if dest:
            verb = "COPY" if self.fb_mode == "copy" else "MOVE"
            items.append(Opt(f"[ {verb} HERE ]", lambda: self.do_transfer_op(path), "", "warn"))
        elif parent_ok:
            items.append(Opt("[ THIS FOLDER... ]", lambda: self.show(lambda: self.file_menu(path)), "COPY, MOVE, DELETE"))
        try:
            entries = self.list_dir(path)
        except OSError as e:
            entries = []
            items.append(Line("CANNOT READ: " + (e.strerror or str(e)).upper(), "bad"))
        if len(entries) > 500:
            items.append(Line(f"SHOWING THE FIRST 500 OF {len(entries)}.", "dim"))
        for name, is_dir, size, p in entries[:500]:
            if dest and not is_dir:
                continue
            items.append(Opt(name + ("/" if is_dir else ""),
                             (lambda p=p: self.open_dir(p)) if is_dir else (lambda p=p: self.show(lambda: self.file_menu(p))),
                             size, raw=True))
        if not dest:
            items.append(Opt("[ NEW FOLDER ]", self.new_folder))
            items.append(Opt("[ NEW NOTE ]", self.new_note))
        back = (lambda: self.open_dir(path.parent)) if parent_ok else (lambda: self.show(self.file_roots))
        return View("browse", "FILES // " + (path.name or str(path)), items, back=back,
                    footer=(f"{len(entries)} ITEMS", "[ESC] UP"))

    def list_dir(self, path: Path) -> list:
        """Directory listing, cached until the folder changes (or 5 s pass) so redraws stay cheap."""
        cache = self.__dict__.setdefault("_ul_dircache", {})
        mtime = os.stat(path).st_mtime_ns
        hit = cache.get(str(path))
        if hit and hit[0] == mtime and time.monotonic() - hit[1] < 5:
            return hit[2]
        rows = []
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                    size = "DIR" if is_dir else system.human(e.stat().st_size)
                except OSError:
                    is_dir, size = False, "?"
                rows.append((e.name, is_dir, size, Path(e.path)))
        rows.sort(key=lambda r: (not r[1], r[0].lower()))
        if len(cache) > 50:
            cache.clear()
        cache[str(path)] = (mtime, time.monotonic(), rows)
        return rows

    def file_menu(self, p: Path) -> View:
        try:
            st = p.stat()
            is_dir = p.is_dir()
            info = [Line(p.name, ""), Line(str(p.parent), "dim"),
                    Line(("FOLDER" if is_dir else system.human(st.st_size)) + " · MODIFIED " +
                         datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"), "dim"), Line("")]
        except OSError as e:
            return View("file", "FILE", [Line("GONE: " + str(e).upper(), "bad"), Opt("BACK", lambda: self.open_dir(p.parent))],
                        back=lambda: self.open_dir(p.parent))
        self.fb_src = p
        opts = []
        if is_dir:
            opts.append(Opt("OPEN", lambda: self.open_dir(p)))
        else:
            opts.append(Opt("VIEW", lambda: self.view_file(p)))
            opts.append(Opt("SEND OVER WAN", lambda: self.show(lambda: self.transfer(p))))
        opts += [
            Opt("COPY TO...", lambda: self.pick_dest("copy")),
            Opt("MOVE TO...", lambda: self.pick_dest("move")),
            Opt("RENAME", lambda: self.rename(p)),
            Opt("DELETE", lambda: self.delete(p), style="bad"),
        ]
        return View("file", "FILE // " + p.name, info + opts, back=lambda: self.open_dir(p.parent))

    def pick_dest(self, mode: str) -> None:
        self.fb_mode = mode
        self.show(self.file_roots)

    def unique(self, target: Path) -> Path:
        if not target.exists():
            return target
        stem, suf = target.stem, target.suffix
        for i in range(2, 1000):
            t = target.with_name(f"{stem} ({i}){suf}")
            if not t.exists():
                return t
        return target

    def do_transfer_op(self, dest_dir: Path) -> None:
        src, mode = self.fb_src, self.fb_mode
        self.fb_mode = "browse"
        target = self.unique(dest_dir / src.name)
        if src.is_dir():
            try:
                inside = dest_dir.resolve() == src.resolve() or src.resolve() in dest_dir.resolve().parents
            except OSError:
                inside = False
            if inside:
                self.message("FILES", ["CANNOT PUT A FOLDER INSIDE ITSELF."], lambda: self.open_dir(dest_dir), "bad")
                return
        job = {"done": 0, "total": 1, "error": "", "finished": False, "name": src.name}
        self.job = job

        def work():
            files = []
            if src.is_dir():
                for root, _, names in os.walk(src):
                    for n in names:
                        fp = Path(root) / n
                        files.append((fp, target / fp.relative_to(src)))
                target.mkdir(parents=True, exist_ok=True)
            else:
                files.append((src, target))
            job["total"] = max(1, sum(f.stat().st_size for f, _ in files if f.exists()))
            if mode == "move":
                try:
                    os.rename(src, target)  # same drive: instant
                    job["done"] = job["total"]
                    return "moved"
                except OSError:
                    pass
            for f, t in files:
                if not f.exists():          # broken link: skip it rather than fail the whole copy
                    job["skipped"] = job.get("skipped", 0) + 1
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(f, "rb") as a, open(t, "wb") as b:
                        while chunk := a.read(1024 * 1024):
                            b.write(chunk)
                            job["done"] += len(chunk)
                except BaseException:
                    t.unlink(missing_ok=True)   # never leave a half-written file behind
                    raise
                try:
                    shutil.copystat(f, t)
                except OSError:
                    pass                        # FAT/exFAT sticks can't keep all permissions
            os.sync() if hasattr(os, "sync") else None
            if mode == "move":
                shutil.rmtree(src) if src.is_dir() else src.unlink()
            return "copied"

        def done(result):
            job["finished"] = True
            if isinstance(result, Exception):
                job["error"] = str(result).upper()
                self.sfx("buzz")
            else:
                self.sfx("chirp")
                self.hook("file.copied", f"{'moved' if mode == 'move' else 'copied'} {src.name} to {dest_dir}",
                          {"source": str(src), "target": str(target), "mode": mode})
            self.redraw()

        def screen():
            pct = job["done"] / job["total"] * 100
            items = [Line(("MOVING " if mode == "move" else "COPYING ") + job["name"]), Line("TO " + str(dest_dir), "dim"), Line(""),
                     Line(f"[{bar(pct)}] {pct:3.0f}%  {system.human(job['done'])}")]
            if job["error"]:
                items += [Line(""), Line("FAILED: " + job["error"], "bad")]
            elif job["finished"]:
                on_usb = any(d.mountpoint and str(dest_dir).startswith(d.mountpoint) for d in self.drives)
                items += [Line(""), Line("DONE." + (f" SKIPPED {job['skipped']} BROKEN LINKS." if job.get("skipped") else ""))]
                if on_usb:
                    items.append(Line("EJECT THE DRIVE IN USB DRIVES BEFORE UNPLUGGING IT.", "dim"))
            if job["finished"]:
                items += [Opt("OPEN DESTINATION", lambda: self.open_dir(dest_dir)), Opt("MAIN MENU", lambda: self.show(self.main))]
            return View("copy", "FILES // " + mode.upper(), items, locked=not job["finished"],
                        back=lambda: self.open_dir(dest_dir), footer=("", "[ESC] BACK" if job["finished"] else "WORKING"))

        self.show(screen)
        self.every(0.2, lambda: (not job["finished"]) and self.redraw())
        self.bg(work, done)

    def rename(self, p: Path) -> None:
        def submit(name):
            if not name or "/" in name:
                self.toast("INVALID NAME")
                return
            target = p.with_name(name)
            if target.exists():
                self.toast("A FILE WITH THAT NAME EXISTS")
                return
            try:
                p.rename(target)
                self.show(lambda: self.file_menu(target))
            except OSError as e:
                self.toast("RENAME FAILED: " + (e.strerror or str(e)))
        self.prompt("FILES // RENAME", "NEW NAME FOR " + p.name, submit, lambda: self.show(lambda: self.file_menu(p)), p.name)

    def delete(self, p: Path) -> None:
        def yes():
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                if hasattr(os, "sync"):
                    os.sync()
                self.hook("file.deleted", f"deleted {p.name}", {"path": str(p)})
                self.toast("DELETED " + p.name)
            except OSError as e:
                self.toast("DELETE FAILED: " + (e.strerror or str(e)))
            self.open_dir(p.parent)
        self.confirm("CONFIRM", "DELETE " + p.name + "?", "THIS CANNOT BE UNDONE.", "YES, DELETE", yes,
                     lambda: self.show(lambda: self.file_menu(p)))

    def new_folder(self) -> None:
        here = self.fb_path

        def submit(name):
            if not name or "/" in name:
                self.toast("INVALID NAME")
                return
            try:
                (here / name).mkdir()
                self.open_dir(here)
            except OSError as e:
                self.toast("FAILED: " + (e.strerror or str(e)))
        self.prompt("FILES // NEW FOLDER", "FOLDER NAME", submit, lambda: self.open_dir(here))

    def new_note(self) -> None:
        here = self.fb_path

        def submit(name):
            if not name or "/" in name:
                self.toast("INVALID NAME")
                return
            if "." not in name:
                name += ".txt"
            target = self.unique(here / name)

            def save(lines):
                try:
                    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    if hasattr(os, "sync"):
                        os.sync()
                    self.toast("SAVED " + target.name)
                except OSError as e:
                    self.toast("SAVE FAILED: " + (e.strerror or str(e)))
                self.open_dir(here)
            self.editor("NOTE // " + target.name, save, lambda: self.open_dir(here))
        self.prompt("FILES // NEW NOTE", "FILE NAME", submit, lambda: self.open_dir(here), hint=".TXT IS ADDED IF YOU LEAVE IT OFF")

    def editor(self, title: str, on_save, back) -> None:
        st = {"lines": [], "buf": ""}

        def char(c):
            st["buf"] += c
            self.redraw()

        def backspace():
            if st["buf"]:
                st["buf"] = st["buf"][:-1]
                self.redraw()
                return True
            if st["lines"]:
                st["buf"] = st["lines"].pop()
                self.redraw()
                return True
            return True

        def enter():
            st["lines"].append(st["buf"])
            st["buf"] = ""
            self.redraw()

        def finish():
            lines = st["lines"] + ([st["buf"]] if st["buf"] else [])
            if not any(l.strip() for l in lines):
                self.toast("NOTHING TYPED, NOTHING SAVED")
                back()
                return
            on_save(lines)

        self.show(lambda: View("editor", title, [Log([Line(l) for l in st["lines"]], top=True), Input("", st["buf"])],
                               footer=("[ENTER] NEW LINE", "[ESC] SAVE"), back=finish,
                               on_enter=enter, on_char=char, on_backspace=backspace))

    def view_file(self, p: Path) -> None:
        try:
            with open(p, "rb") as f:
                data = f.read(256 * 1024)
        except OSError as e:
            self.toast("CANNOT OPEN: " + (e.strerror or str(e)))
            return
        if b"\0" in data[:4096]:
            lines = ["BINARY FILE · " + system.human(p.stat().st_size), ""]
            for i in range(0, min(len(data), 512), 8):
                chunk = data[i:i + 8]
                lines.append(f"{i:06X}  " + " ".join(f"{b:02X}" for b in chunk))
        else:
            lines = data.decode("utf-8", errors="replace").replace("\t", "    ").splitlines() or [""]
        st = {"off": 0}

        def key(k):
            page = max(1, self.body_h - 1)
            step = {"up": -1, "down": 1, "pageup": -page, "pagedown": page, "home": -10**9, "end": 10**9}.get(k)
            if step is None:
                return False
            st["off"] = max(0, min(max(0, len(lines) - page), st["off"] + step))
            self.redraw()
            return True

        def screen():
            page = max(1, self.body_h - 1)
            width = max(10, self.term.content_size.width if hasattr(self, "term") else 60)
            rows: list[str] = []
            i = st["off"]
            while i < len(lines) and len(rows) < page:   # wrap long lines so nothing falls off the bottom
                rows += self._wrap(lines[i][:2000], width)
                i += 1
            return View("viewer", "VIEW // " + p.name, [Line(r) for r in rows[:page]],
                        footer=(f"LINE {st['off'] + 1}/{len(lines)}", "[▲▼] SCROLL [ESC] BACK"),
                        back=lambda: self.show(lambda: self.file_menu(p)), on_key=key, on_enter=lambda: None)
        self.show(screen)

    # ================================================================ USB
    def usb_loop(self) -> None:
        first = True
        while not self._ul_stop.wait(0 if first else 2):
            drives = system.list_drives()
            old = {d.path: d for d in self.drives}
            new = {d.path: d for d in drives}
            if first:
                first = False
                self.ui(self.set_drives, drives, [], [])
                continue
            added = [d for p, d in new.items() if p not in old]
            removed = [d for p, d in old.items() if p not in new]
            changed = added or removed or any(new[p].mountpoint != old[p].mountpoint for p in new if p in old)
            if changed:
                self.ui(self.set_drives, drives, added, removed)

    def set_drives(self, drives, added, removed) -> None:
        self.drives = drives
        for d in added:
            self.sfx("chirp")
            self.toast(f"USB INSERTED: {d.name} ({system.human(d.size)})")
            self.hook("usb.inserted", f"USB inserted: {d.name}", {"device": d.path, "label": d.label, "size": d.size})
            if self.cfg["usb_automount"] == "ON" and not d.mountpoint:
                self.mount_then(d, None)
        for d in removed:
            self.toast(f"USB REMOVED: {d.name}")
            self.hook("usb.removed", f"USB removed: {d.name}", {"device": d.path})
            if self.view and self.view.id in ("browse", "file", "viewer") and d.mountpoint and \
                    str(getattr(self, "fb_path", "")).startswith(d.mountpoint):
                self.show(self.file_roots)
        if self.view and self.view.id in ("main", "usb", "roots", "drive"):
            self.redraw()

    def mount_then(self, d: system.Drive, then) -> None:
        self.toast("MOUNTING " + d.name + "...")

        def done(result):
            ok, out = result if isinstance(result, tuple) else (False, str(result))
            if ok:
                self.toast("MOUNTED " + d.name)
                if then:
                    then(Path(d.mountpoint))
                elif self.view and self.view.id in ("usb", "drive", "roots", "main"):
                    self.redraw()
            else:
                self.sfx("buzz")
                self.toast("MOUNT FAILED: " + out.splitlines()[-1][:50] if out else "MOUNT FAILED")
        self.bg(lambda: system.mount(d), done)

    def usb(self) -> View:
        items = []
        if not system.IS_LINUX:
            items.append(Line("USB ACCESS NEEDS THE LINUX DEVICE.", "warn"))
        elif not self.drives:
            items += [Line("NO USB DRIVES FOUND."), Line("PLUG ONE IN. IT SHOWS UP HERE BY ITSELF.", "dim")]
        else:
            items.append(Line("NAME                    STATE", "dim"))
        for d in self.drives:
            items.append(Opt(f"{d.name}  {system.human(d.size)}", lambda d=d: self.show(lambda: self.drive(d)),
                             "MOUNTED" if d.mountpoint else "NOT MOUNTED", "" if d.mountpoint else "warn"))
        return View("usb", "USB // DRIVES", items, footer=(f"AUTO-MOUNT {self.cfg['usb_automount']}", "[ESC] BACK"))

    def drive(self, d: system.Drive) -> View:
        current = next((x for x in self.drives if x.path == d.path), None)
        if current is None:
            return View("drive", "USB // " + d.name, [Line("THIS DRIVE WAS REMOVED.", "warn"), Line(""),
                                                       Opt("BACK TO USB DRIVES", lambda: self.show(self.usb))],
                        back=lambda: self.show(self.usb))
        d = current
        items = [Line(d.name), Line(f"{d.path} · {d.fstype.upper()} · {system.human(d.size)}", "dim"),
                 Line("MOUNTED AT " + d.mountpoint if d.mountpoint else "NOT MOUNTED", "dim" if d.mountpoint else "warn")]
        if d.mountpoint:
            try:
                du = shutil.disk_usage(d.mountpoint)
                items.append(Line(f"FREE {system.human(du.free)} OF {system.human(du.total)}  [{bar(du.used / du.total * 100, 12)}]", "dim"))
            except OSError:
                pass
        items.append(Line(""))
        if d.mountpoint:
            items.append(Opt("OPEN FILES", lambda: self.open_dir(Path(d.mountpoint))))
            items.append(Opt("UNMOUNT", lambda: self.usb_action(d, system.unmount, "UNMOUNTED")))
        else:
            items.append(Opt("MOUNT AND OPEN", lambda: self.mount_then(d, self.open_dir)))
        items.append(Opt("EJECT SAFELY", lambda: self.usb_action(d, system.eject, "SAFE TO REMOVE"), style="warn"))
        return View("drive", "USB // " + d.name, items, back=lambda: self.show(self.usb))

    def usb_action(self, d, fn, ok_text) -> None:
        self.toast("WORKING...")

        def done(result):
            ok, out = result if isinstance(result, tuple) else (False, str(result))
            if ok:
                d.mountpoint = ""
                self.toast(ok_text + ": " + d.name)
                self.sfx("chirp")
            else:
                self.sfx("buzz")
                self.toast("FAILED: " + (out.splitlines()[-1][:50] if out else "?"))
            self.show(self.usb)
        self.bg(lambda: fn(d), done)

    # ================================================================ transfer (WAN)
    def transfer(self, p: Path) -> View:
        back = lambda: self.show(lambda: self.file_menu(p))
        items = [Line("FILE: " + p.name), Line("SEND TO:", "dim")]
        items.append(Opt("TAILNET DEVICE (TAILDROP)", lambda: self.pick_peer(p), "TAILSCALE" if system.have("tailscale") else "NOT INSTALLED"))
        for t in self.cfg["rsync_targets"]:
            items.append(Opt(t, lambda t=t: self.run_job("RSYNC", ["rsync", "-ah", "--info=progress2", str(p), t], back),
                             "RSYNC" if system.have("rsync") else "NOT INSTALLED", raw=True))
        items.append(Opt("ADD RSYNC TARGET", lambda: self.prompt("TRANSFER // NEW TARGET", "HOST:/PATH, FOR EXAMPLE pve-3:/tank/inbox",
                                                                 lambda v: self.add_target(v, p), lambda: self.show(lambda: self.transfer(p)))))
        items.append(Opt("ANYONE (CROC CODE)", lambda: self.run_job("CROC", ["croc", "send", str(p)], back),
                         "CROC" if system.have("croc") else "NOT INSTALLED"))
        return View("transfer", "TRANSFER // WAN", items, back=back)

    def add_target(self, value: str, p: Path) -> None:
        if ":" not in value:
            self.toast("USE HOST:/PATH")
            return
        self.cfg["rsync_targets"].append(value)
        self.cfg.save()
        self.show(lambda: self.transfer(p))

    def pick_peer(self, p: Path) -> None:
        self.toast("ASKING TAILSCALE...")

        def done(result):
            if isinstance(result, Exception):
                result = ("ERROR", "", [])
            state, _, peers = result
            back = lambda: self.show(lambda: self.transfer(p))
            if state != "RUNNING":
                self.message("TAILDROP", [f"TAILSCALE IS {state}.", "TURN IT ON IN THE VPN MENU."], back, "warn")
                return
            items = [Line("PICK A DEVICE:", "dim")] + [
                Opt(h, lambda h=h: self.run_job("TAILDROP", ["tailscale", "file", "cp", str(p), f"{h}:"], back),
                    "ONLINE" if on else "OFFLINE", "" if on else "dim", raw=True) for h, on in peers]
            self.show(lambda: View("peers", "TAILDROP // " + p.name, items, back=back))
        self.bg(system.tailscale_status, done)

    def run_job(self, title: str, args: list, back) -> None:
        """Run a command and stream its output to the screen. ESC cancels while it runs."""
        job = {"out": [], "done": False, "ok": None, "proc": None}

        def work():
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except FileNotFoundError:
                job["out"].append(args[0] + " is not installed.")
                return False
            job["proc"] = proc
            buf = ""
            fd = proc.stdout.fileno()
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buf += chunk.decode(errors="replace").replace("\r", "\n")
                *lines, buf = buf.split("\n")
                job["out"] = (job["out"] + [l.strip() for l in lines if l.strip()])[-200:]
            if buf.strip():
                job["out"].append(buf.strip())
            return proc.wait() == 0

        def done(ok):
            job["done"], job["ok"] = True, ok is True
            self.sfx("chirp" if job["ok"] else "buzz")
            self.redraw()

        def cancel():
            if not job["done"] and job["proc"]:
                job["proc"].terminate()
            back()

        def screen():
            state = "RUNNING..." if not job["done"] else ("DONE." if job["ok"] else "FAILED.")
            return View("job", "TRANSFER // " + title, [Line(" ".join(args[:2]).upper(), "dim"),
                        Log([Line(l) for l in job["out"]], top=True), Line(state, "" if job["ok"] is not False else "bad")],
                        footer=("", "[ESC] CANCEL" if not job["done"] else "[ESC] BACK"), back=cancel, on_enter=lambda: None)
        self.show(screen)
        self.every(0.3, lambda: (not job["done"]) and self.redraw())
        self.bg(work, done)

    # ================================================================ messages
    def hook_by_id(self, hid: str):
        return next((h for h in self.cfg["webhooks"] if h["id"] == hid), None)

    def save_threads(self) -> None:
        storage.save_messages(self.threads)

    def inbox(self) -> View:
        items = [Line("OUTGOING VIA WEBHOOKS · NTFY THREADS ARE TWO-WAY", "dim")]
        for t in self.threads:
            h = self.hook_by_id(t.get("hook", ""))
            tag = f"{t['unread']} NEW" if t.get("unread") else (h["format"] if h else "LOCAL")
            items.append(Opt(t["name"], lambda t=t: self.show(lambda: self.thread(t)), tag, "warn" if t.get("unread") else ""))
        items.append(Opt("NEW THREAD", self.new_thread))
        return View("inbox", "MESSAGES // INBOX", items)

    def new_thread(self) -> None:
        def submit(name):
            if not name:
                return
            t = {"id": uuid.uuid4().hex[:8], "name": name.upper(), "hook": "", "msgs": []}
            self.threads.append(t)
            self.save_threads()
            self.show(lambda: self.thread(t))
        self.prompt("MESSAGES // NEW THREAD", "THREAD NAME", submit, lambda: self.show(self.inbox))

    def msg_line(self, m: dict, name: str) -> Line:
        if m.get("me"):
            st = m.get("status", "")
            return Line("YOU> " + m["t"] + (f"  [{st}]" if st and st != "SENT" else ""), "bad" if st == "FAILED" else "dim")
        return Line(name.split(" ")[0][:10] + "> " + m["t"])

    def thread(self, t: dict) -> View:
        if t.get("unread"):
            t["unread"] = 0
            self.save_threads()
        h = self.hook_by_id(t.get("hook", ""))
        msgs = [self.msg_line(m, t["name"]) for m in t["msgs"][-50:]] or [Line("NO MESSAGES YET.", "dim")]
        return View("thread", "MSG // " + t["name"], [
            Log(msgs), Line(""),
            Opt("WRITE MESSAGE", lambda: self.compose_msg(t)),
            Opt("LINK WEBHOOK", lambda: self.show(lambda: self.link_hook(t)), h["name"] if h else "NONE"),
            Opt("DELETE THREAD", lambda: self.confirm("CONFIRM", f"DELETE {t['name']}?", "ITS MESSAGES ARE REMOVED FROM THIS DEVICE.",
                                                      "YES, DELETE", lambda: self.delete_thread(t), lambda: self.show(lambda: self.thread(t))), style="bad"),
        ], back=lambda: self.show(self.inbox))

    def delete_thread(self, t) -> None:
        self.threads = [x for x in self.threads if x is not t]
        self.save_threads()
        self.show(self.inbox)

    def link_hook(self, t: dict) -> View:
        def pick(hid):
            t["hook"] = hid
            if hid:
                t["since"] = str(int(time.time()))
            self.save_threads()
            self.show(lambda: self.thread(t))
        items = [Line("SEND THIS THREAD'S MESSAGES TO:", "dim"), Opt("NONE (LOCAL ONLY)", lambda: pick(""))]
        for h in self.cfg["webhooks"]:
            items.append(Opt(h["name"], lambda h=h: pick(h["id"]), h["format"]))
        if not self.cfg["webhooks"]:
            items.append(Line("NO WEBHOOKS YET. ADD ONE IN SETTINGS > WEBHOOKS.", "warn"))
        return View("linkhook", "MSG // LINK", items, back=lambda: self.show(lambda: self.thread(t)))

    def compose_msg(self, t: dict) -> None:
        st = {"buf": ""}

        def char(c):
            st["buf"] += c
            self.redraw()

        def backspace():
            if st["buf"]:
                st["buf"] = st["buf"][:-1]
                self.redraw()
                return True
            return False

        def send():
            text = st["buf"].strip()
            if not text:
                return
            h = self.hook_by_id(t.get("hook", ""))
            m = {"me": True, "t": text, "at": int(time.time()), "status": "SENDING" if h else "LOCAL"}
            t["msgs"].append(m)
            self.save_threads()
            self.sfx("ok")
            self.show(lambda: self.thread(t))
            self.hook("message.sent", f"message to {t['name']}: {text}", {"thread": t["name"], "text": text},
                      exclude=h["id"] if h else "")
            if h:
                def work():
                    return webhooks.send(h, "message.sent", text, {"thread": t["name"]}, self.cfg["device_name"])

                def done(result):
                    ok = isinstance(result, tuple) and result[0]
                    m["status"] = "SENT" if ok else "FAILED"
                    if ok and h["format"] == "NTFY":
                        try:
                            t.setdefault("sent_ids", []).append(json.loads(result[2]).get("id", ""))
                            t["sent_ids"] = t["sent_ids"][-50:]
                        except ValueError:
                            pass
                    self.save_threads()
                    self.cfg.save()
                    if self.view and self.view.id == "thread":
                        self.redraw()
                self.bg(work, done)

        self.show(lambda: View("compose", "TO: " + t["name"], [
            Log([self.msg_line(m, t["name"]) for m in t["msgs"][-6:]]), Line(""), Input("YOU> ", st["buf"]),
        ], footer=("[ENTER] SEND", "[ESC] CANCEL"), back=lambda: self.show(lambda: self.thread(t)),
            on_enter=send, on_char=char, on_backspace=backspace))

    def ntfy_loop(self) -> None:
        """Pull replies for threads linked to an ntfy topic."""
        while not self._ul_stop.wait(20):
            for t in list(self.threads):
                h = self.hook_by_id(t.get("hook", ""))
                if not h or h.get("format") != "NTFY":
                    continue
                try:
                    msgs = webhooks.ntfy_poll(h["url"], t.get("since") or "10m")
                except Exception:
                    continue
                new = [m for m in msgs if m["id"] not in t.get("sent_ids", []) and m["id"] not in t.get("seen_ids", [])]
                if msgs:
                    t["since"] = msgs[-1]["id"]
                if new:
                    self.ui(self.receive, t, new)

    def receive(self, t: dict, new: list) -> None:
        for m in new:
            t["msgs"].append({"me": False, "t": m["message"], "at": m["time"]})
            t.setdefault("seen_ids", []).append(m["id"])
        t["seen_ids"] = t["seen_ids"][-100:]
        viewing = self.view and self.view.id == "thread" and self.view.title.endswith(t["name"])
        if not viewing:
            t["unread"] = t.get("unread", 0) + len(new)
            self.toast(f"NEW MESSAGE: {t['name']}")
        self.sfx("chirp")
        self.save_threads()
        if self.view and self.view.id in ("thread", "inbox", "main"):
            self.redraw()

    # ================================================================ nodes
    def node_loop(self) -> None:
        first = True
        while not self._ul_stop.wait(0 if first else 20):
            nodes = list(self.cfg["nodes"])
            if nodes:
                with ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
                    list(pool.map(lambda n: self.ping_node(n, notify=not first), nodes))
            first = False
            self.ui(lambda: self.view and self.view.id in ("main", "nodes", "node") and self.redraw())

    def ping_node(self, n: dict, notify: bool = True) -> None:
        lat = system.ping(n["host"])
        old = self.node_state.get(n["name"], {})
        st = {"up": lat is not None, "ms": lat, "checked": time.time(),
              "seen": time.time() if lat is not None else old.get("seen")}
        self.node_state[n["name"]] = st
        if notify and old and old.get("up") != st["up"]:
            ev = "node.up" if st["up"] else "node.down"
            self.hook(ev, f"{n['name']} is {'online' if st['up'] else 'OFFLINE'}", {"node": n["name"], "host": n["host"]})
            if not st["up"]:
                self.ui(self.toast, f"{n['name']} WENT OFFLINE")

    def nodes(self) -> View:
        items = [Line("NAME         HOST            STATE", "dim")]
        for n in self.cfg["nodes"]:
            st = self.node_state.get(n["name"])
            if not st:
                tag, style = "CHECKING", "dim"
            elif st["up"]:
                tag, style = f"{st['ms']:.0f} MS", ""
            else:
                tag, style = "OFFLINE", "bad"
            items.append(Opt(f"{n['name']:<12} {n['host'][:15]}", lambda n=n: self.show(lambda: self.node(n)), tag, style))
        items.append(Line(""))
        items.append(Line("EDIT THE LIST IN " + str(storage.Config.path), "dim"))
        return View("nodes", "NODES // NETWORK", items)

    def node(self, n: dict) -> View:
        st = self.node_state.get(n["name"], {})
        seen = datetime.datetime.fromtimestamp(st["seen"]).strftime("%H:%M:%S") if st.get("seen") else "NEVER"
        items = [Line("ROLE:   " + n.get("role", "")), Line("HOST:   " + n["host"]),
                 Line("STATE:  " + ("ONLINE" if st.get("up") else "OFFLINE" if st else "CHECKING"), "" if st.get("up") else "bad"),
                 Line("PING:   " + (f"{st['ms']:.1f} MS" if st.get("up") else "-")), Line("SEEN:   " + seen, "dim"), Line("")]

        def ping_now():
            self.toast("PINGING " + n["host"] + "...")
            self.bg(lambda: self.ping_node(n), lambda _: self.redraw())
        items.append(Opt("PING NOW", ping_now))
        if system.have("ssh"):
            items.append(Opt("OPEN SSH SHELL", lambda: self.shell(["ssh", n["host"]])))
        if n.get("mac"):
            def wake():
                ok, msg = system.wake_on_lan(n["mac"])
                self.toast(msg)
            items.append(Opt("WAKE (WOL)", wake, n["mac"], raw=True))
        else:
            items.append(Line("ADD A MAC ADDRESS IN CONFIG.JSON TO WAKE IT.", "dim"))
        return View("node", "NODE // " + n["name"], items, back=lambda: self.show(self.nodes))

    def shell(self, args: list) -> None:
        """Hand the screen to another program (ssh, a shell), then come back."""
        try:
            with self.suspend():
                subprocess.call(args)
        except Exception as e:
            self.toast("CANNOT OPEN SHELL: " + str(e)[:40])
        self.redraw()

    # ================================================================ VPN
    def open_vpn(self) -> None:
        self.show(self.vpn)
        self.refresh_vpn()

    def refresh_vpn(self) -> None:
        def work():
            ts_state, ip, peers = system.tailscale_status()
            tg = system.twingate_status()
            active = "TAILSCALE" if ts_state == "RUNNING" else "TWINGATE" if ("ONLINE" in tg or "CONNECTED" in tg) else "OFF"
            return {"ts": ts_state, "ip": ip, "peers": peers, "tg": tg, "active": active}

        def done(info):
            if isinstance(info, dict):
                self.vpn_info = info
            if self.view and self.view.id in ("vpn", "main"):
                self.redraw()
        self.bg(work, done)

    def vpn(self) -> View:
        i = self.vpn_info
        if not i:
            return View("vpn", "VPN // TUNNEL", [Line("CHECKING TUNNELS...", "dim")])
        mark = lambda v: "(•)" if i["active"] == v else "( )"
        online = sum(1 for _, on in i["peers"] if on)

        def set_vpn(target):
            self.toast("SWITCHING TO " + target + "...")
            self.sfx("clack")

            def done(result):
                ok, out = result if isinstance(result, tuple) else (False, str(result))
                if ok:
                    self.hook("vpn.changed", f"VPN set to {target}", {"vpn": target})
                    self.toast("VPN: " + target)
                else:
                    self.sfx("buzz")
                    hint = " (RUN: sudo tailscale set --operator=$USER)" if "operator" in out.lower() or "denied" in out.lower() else ""
                    self.toast("FAILED: " + (out.splitlines()[-1][:40] if out else "?") + hint, 8)
                self.refresh_vpn()
            self.bg(lambda: system.vpn_set(target), done)

        return View("vpn", "VPN // TUNNEL", [
            Line("ONE TUNNEL AT A TIME.", "dim"),
            Line(f"TAILSCALE: {i['ts']}" + (f" · {i['ip']} · {online} PEERS ONLINE" if i["ip"] else "")),
            Line(f"TWINGATE:  {i['tg']}"), Line(""),
            Opt(mark("TAILSCALE") + " TAILSCALE", lambda: set_vpn("TAILSCALE"), "" if system.have("tailscale") else "NOT INSTALLED"),
            Opt(mark("OFF") + " OFF", lambda: set_vpn("OFF")),
            Opt(mark("TWINGATE") + " TWINGATE", lambda: set_vpn("TWINGATE"), "" if system.have("twingate") else "NOT INSTALLED"),
            Opt("REFRESH", self.refresh_vpn),
        ])

    # ================================================================ holotape
    def all_tapes(self) -> list:
        return BUILTIN_TAPES + self.user_tapes

    def deck(self) -> View:
        items = [Line("INSERT A TAPE.  * = YOUR RECORDINGS", "dim")]
        for t in self.all_tapes():
            items.append(Opt(("" if t.get("builtin") else "* ") + t["name"], lambda t=t: self.show(lambda: self.tape_menu(t)),
                             ("♪ " if t.get("audio") else "") + ts(t.get("secs", 0))))
        items.append(Opt("RECORD NEW TAPE", self.record, "REC", "bad"))
        items.append(Opt("DECK SETTINGS", lambda: self.show(self.deck_settings)))
        return View("deck", "HOLOTAPE // DECK", items)

    def tape_menu(self, t: dict) -> View:
        items = [Line(t["name"]), Line(f"{ts(t.get('secs', 0))} · {len(t.get('lines', []))} LINES" +
                                       (" · AUDIO " + t.get("quality", "") if t.get("audio") else " · TEXT ONLY"), "dim"), Line(""),
                 Opt("PLAY", lambda: self.play(t))]
        if not t.get("builtin"):
            mounted = [d for d in self.drives if d.mountpoint]
            if mounted:
                for d in mounted:
                    items.append(Opt("EXPORT TO USB " + d.name, lambda d=d: self.export_tape(t, d)))
            else:
                items.append(Line("PLUG IN A USB DRIVE TO EXPORT THIS TAPE.", "dim"))
            items.append(Opt("RENAME", lambda: self.rename_tape(t)))
            items.append(Opt("ERASE TAPE", lambda: self.confirm("CONFIRM", f"ERASE {t['name']}?", "THIS CANNOT BE UNDONE.", "YES, ERASE",
                                                                lambda: self.erase_tapes([t]), lambda: self.show(lambda: self.tape_menu(t))), style="bad"))
        return View("tapemenu", "HOLOTAPE // " + t["name"], items, back=lambda: self.show(self.deck))

    def rename_tape(self, t) -> None:
        def submit(name):
            if name:
                t["name"] = name.upper()
                storage.save_tape(t)
            self.show(lambda: self.tape_menu(t))
        self.prompt("HOLOTAPE // RENAME", "NEW NAME", submit, lambda: self.show(lambda: self.tape_menu(t)), t["name"])

    def export_tape(self, t, d) -> None:
        def work():
            out = Path(d.mountpoint) / "UPLINK_TAPES"
            out.mkdir(exist_ok=True)
            base = t["name"].replace("/", "-")
            (out / f"{base}.txt").write_text("\n".join(t.get("lines", [])) + "\n", encoding="utf-8")
            if t.get("audio") and Path(t["audio"]).exists():
                shutil.copy2(t["audio"], out / f"{base}.wav")
            if hasattr(os, "sync"):
                os.sync()
            return str(out)

        def done(r):
            if isinstance(r, Exception):
                self.sfx("buzz")
                self.toast("EXPORT FAILED: " + str(r)[:40])
            else:
                self.sfx("chirp")
                self.toast("EXPORTED TO " + r)
                self.hook("file.copied", f"exported tape {t['name']} to USB", {"target": r})
        self.bg(work, done)

    def erase_tapes(self, tapes) -> None:
        for t in tapes:
            for p in (t.get("_path"), t.get("audio")):
                if p:
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass
        self.user_tapes = storage.load_tapes()
        self.show(self.deck)

    def play(self, t: dict) -> None:
        lines = t.get("lines", [])
        total = max(1, sum(len(l) for l in lines))
        player = None
        if t.get("audio") and audio.can_play() and Path(t["audio"]).exists():
            player = audio.Player(t["audio"])
            player.start()
        st = {"li": 0, "ci": 0, "playing": True, "done": False, "tick": 0, "typed": 0,
              "elapsed": 0.0, "last": time.monotonic()}
        secs = max(1.0, float(t.get("secs") or 1))
        anim = self.fx("animations")
        speed = SPEED[self.cfg["speed"] if self.cfg["speed"] in SPEED else "NORMAL"] or 0.01
        self.sfx("clack")

        def step():
            now = time.monotonic()
            dt, st["last"] = now - st["last"], now
            if not st["playing"] or st["done"]:
                return
            st["tick"] += 1
            if player:
                st["elapsed"] = min(secs, st["elapsed"] + dt)
                frac = st["elapsed"] / secs
                shown_chars = int(frac * total)
                st["typed"] = shown_chars
                if not player.alive() or st["elapsed"] >= secs:
                    st["done"], st["playing"] = True, False
                    st["typed"] = total
                    self.sfx("clack")
            else:
                if st["li"] >= len(lines):
                    st["done"], st["playing"] = True, False
                    self.sfx("clack")
                elif not anim:
                    if st["tick"] % max(1, int(1.2 / speed)) == 0 or st["tick"] == 1:
                        st["typed"] += len(lines[st["li"]])
                        st["li"] += 1
                elif st["ci"] < len(lines[st["li"]]):
                    st["ci"] += 1
                    st["typed"] += 1
                elif st["tick"] % 12 == 0:
                    st["li"] += 1
                    st["ci"] = 0
            self.redraw()

        def visible():
            out, left = [], st["typed"]
            for l in lines:
                if left <= 0:
                    break
                out.append(l[:left])
                left -= len(l)
            return out

        def toggle():
            if st["done"]:
                self.play(t)
                return
            st["playing"] = not st["playing"]
            if player:
                player.pause(not st["playing"])
            self.sfx("clack")
            self.redraw()

        def eject():
            if player:
                player.stop()
            self.sfx("clack")
            self.show(lambda: self.tape_menu(t))

        def screen():
            spin = "|/-\\"
            r = spin[(st["tick"] // 2) % 4] if (st["playing"] and anim) else "|"
            frac = min(1.0, st["typed"] / total) if not player else st["elapsed"] / secs
            shown = visible()
            if player and not lines:
                shown = ["(AUDIO ONLY)"]
            return View("tape", "HOLOTAPE // " + t["name"], [
                Line(f"   ( {r} )=========( {r} )") if not self.plain else Line(""),
                Line(f"[{bar(frac * 100)}] {ts(frac * secs)}/{ts(secs)}", "dim"),
                Line("END OF TAPE." if st["done"] else "> PLAYING" + (" AUDIO" if player else "") if st["playing"] else "> PAUSED",
                     "warn" if st["done"] or not st["playing"] else ""),
                Line(""), Log([Line(l) for l in shown], top=True),
            ], footer=("[ENTER] " + ("REPLAY" if st["done"] else "PAUSE" if st["playing"] else "PLAY"), "[ESC] EJECT"),
                back=eject, on_enter=toggle)
        self.show(screen)
        self.every(0.1 if player else speed, step)

    def record(self) -> None:
        tid = time.strftime("%Y%m%d-%H%M%S")
        use_mic = self.cfg["mic"] == "ON" and (self.mic_ok if self.mic_ok is not None else audio.can_record())
        rec = None
        if use_mic:
            storage.TAPES_DIR.mkdir(parents=True, exist_ok=True)
            rec = audio.Recorder(str(storage.TAPES_DIR / f"{tid}.wav"), self.cfg["quality"])
            if not rec.start():
                self.toast("MIC FAILED: " + rec.error[:40])
                rec = None
        st = {"lines": [], "buf": "", "start": time.monotonic(), "last_key": 0.0}
        self.sfx("rec")

        def char(c):
            st["buf"] += c
            st["last_key"] = time.monotonic()
            self.redraw()

        def backspace():
            if st["buf"]:
                st["buf"] = st["buf"][:-1]
                self.redraw()
            return True

        def enter():
            if st["buf"].strip():
                st["lines"].append(st["buf"].strip())
                st["buf"] = ""
                self.redraw()
            else:
                stop()

        def stop():
            self.stop_timers()
            if st["buf"].strip():
                st["lines"].append(st["buf"].strip())
            secs = rec.stop() if rec else time.monotonic() - st["start"]
            self.sfx("stop")
            if not st["lines"] and not rec:
                self.show(self.deck)
                return
            n = len(self.user_tapes) + 1
            name = ("FIELD LOG " if self.cfg["autoname"] == "ON" else "UNTITLED ") + f"{n:02d}"
            tape = {"id": tid, "name": name, "secs": round(max(1, secs)), "lines": st["lines"],
                    "audio": rec.path if rec else "", "quality": self.cfg["quality"], "created": int(time.time())}
            tape["_path"] = str(storage.save_tape(tape))
            self.user_tapes = storage.load_tapes()
            self.hook("tape.recorded", f"recorded holotape {name} ({ts(secs)})", {"name": name, "seconds": round(secs)})
            saved = next((x for x in self.user_tapes if x["id"] == tid), tape)
            self.show(lambda: View("saved", "HOLOTAPE // SAVED", [
                Line("TAPE SAVED: " + name), Line(f"{ts(secs)} · {len(st['lines'])} LINES" + (" · AUDIO" if rec else ""), "dim"), Line(""),
                Opt("PLAY IT NOW", lambda: self.play(saved)), Opt("BACK TO DECK", lambda: self.show(self.deck)),
            ], back=lambda: self.show(self.deck)))

        def screen():
            secs = time.monotonic() - st["start"]
            if rec:
                level = rec.level
            else:
                level = 60 if time.monotonic() - st["last_key"] < .5 else 8
            rec_style = "bad" if (self.blink_on or self.plain) else "dim"
            if rec and rec.error:
                return View("rec", "HOLOTAPE // RECORDING", [
                    Line("MICROPHONE STOPPED: " + rec.error.upper()[:80], "bad"), Line("YOUR TYPED LINES ARE KEPT.", "dim"),
                    Log([Line(l) for l in st["lines"]], top=True), Input("", st["buf"]),
                ], footer=("[ENTER] NEXT LINE", "[ESC] STOP & SAVE"), back=stop, on_enter=enter, on_char=char, on_backspace=backspace)
            return View("rec", "HOLOTAPE // RECORDING", [
                Line("● REC  " + ts(secs) + ("  MIC" if rec else "  TEXT ONLY"), rec_style),
                Line(f"LEVEL [{bar(level, 14)}]"),
                Line(f"QUALITY: {self.cfg['quality']}" if rec else "NO MICROPHONE: TYPE YOUR LOG", "dim"),
                Line("TYPE NOTES WHILE YOU TALK." if rec else "", "dim"),
                Log([Line(l) for l in st["lines"]], top=True), Input("", st["buf"]),
            ], footer=("[ENTER] NEXT LINE", "[ESC] STOP & SAVE"), back=stop, on_enter=enter, on_char=char, on_backspace=backspace)
        self.show(screen)
        self.every(0.15, self.render_view_rebuild)

    def render_view_rebuild(self) -> None:
        self.redraw()

    def deck_settings(self) -> View:
        mic_note = None
        if self.mic_ok is False:
            mic_note = "NOT FOUND"
        return View("deckset", "HOLOTAPE // DECK SETTINGS", [
            Line("ENTER CHANGES A SETTING.", "dim"),
            self.cycle("RECORD QUALITY", "quality", ["LO-FI", "STANDARD", "HI-FI"], self.deck_settings),
            self.cycle("MICROPHONE", "mic", ["ON", "OFF"], self.deck_settings, mic_note if self.cfg["mic"] == "ON" and mic_note else ""),
            self.cycle("PLAYBACK SPEED", "speed", ["SLOW", "NORMAL", "FAST"], self.deck_settings),
            self.cycle("AUTO-NAME TAPES", "autoname", ["ON", "OFF"], self.deck_settings),
            Opt("ERASE MY RECORDINGS", lambda: self.confirm("CONFIRM", f"ERASE {len(self.user_tapes)} RECORDED TAPES?",
                                                            "BUILT-IN TAPES STAY.", "YES, ERASE ALL",
                                                            lambda: self.erase_tapes(list(self.user_tapes)), lambda: self.show(self.deck_settings)),
                f"{len(self.user_tapes)} TAPES", "warn"),
        ], back=lambda: self.show(self.deck))

    # ================================================================ settings
    def settings(self) -> View:
        hooks = self.cfg["webhooks"]
        fw_tag = f"V{self.update_info['version']} READY" if self.update_info else f"V{__version__}"
        return View("settings", "SETTINGS // SYSTEM", [
            self.cycle("DISPLAY COLOR", "color", ["GREEN", "AMBER", "WHITE", "BLUE"], self.settings,
                       "GREEN (PLAIN)" if self.plain else ""),
            Opt("ACCESSIBILITY", lambda: self.show(self.accessibility), "PLAIN" if self.plain else "EFFECTS ON"),
            Opt("WEBHOOKS", lambda: self.show(self.webhooks), f"{sum(1 for h in hooks if h.get('enabled'))} ACTIVE"),
            self.cycle("USB AUTO-MOUNT", "usb_automount", ["ON", "OFF"], self.settings),
            self.cycle("CLOCK", "clock", ["24H", "12H"], self.settings),
            Opt("UPDATE FIRMWARE", lambda: self.show(self.firmware), fw_tag, "warn" if self.update_info else ""),
            Opt("DEVICE NAME", lambda: self.prompt("SETTINGS // NAME", "SHOWN IN THE TITLE BAR AND IN WEBHOOKS",
                                                   self.set_name, lambda: self.show(self.settings), self.cfg["device_name"]),
                self.cfg["device_name"]),
            Opt("RESTORE DEFAULTS", lambda: self.confirm(
                "CONFIRM", "RESTORE ALL SETTINGS TO DEFAULT?", "WEBHOOKS, NODES, TAPES AND MESSAGES ARE KEPT.",
                "YES, RESTORE", self.restore_defaults, lambda: self.show(self.settings))),
            Opt("ABOUT THIS DEVICE", lambda: self.show(self.about)),
        ])

    def set_name(self, name: str) -> None:
        if name:
            self.cfg["device_name"] = name.upper()[:20]
            self.cfg.save()
        self.show(self.settings)

    def restore_defaults(self) -> None:
        self.cfg.reset()
        self.sfx("clack")
        self.message("SETTINGS", ["DEFAULT SETTINGS RESTORED.", Line("WEBHOOKS, NODES, TAPES AND MESSAGES ARE KEPT.", "dim")],
                     lambda: self.show(self.settings))

    def accessibility(self) -> View:
        a = self.accessibility
        items = [
            self.cycle("PLAIN MODE (REALISM)", "plain", ["OFF", "ON"], a),
            Line("GREEN TEXT ONLY. NO ANIMATION, BLINKING, SOUND OR COLOR." if self.plain
                 else "TURN ON FOR GREEN TEXT ONLY, WITH EVERY EFFECT OFF.", "dim"),
            Line(""),
        ]
        note = "OFF (PLAIN)" if self.plain else ""
        items += [
            self.cycle("ANIMATIONS", "animations", ["ON", "OFF"], a, note),
            self.cycle("BLINKING CURSOR", "cursor_blink", ["ON", "OFF"], a, note),
            self.cycle("SOUNDS", "sounds", ["ON", "OFF"], a, note),
            self.cycle("KEY CLICKS", "key_clicks", ["ON", "OFF"], a, note),
            self.cycle("TEXT SPEED", "text_speed", ["SLOW", "NORMAL", "FAST", "INSTANT"], a, "INSTANT (PLAIN)" if self.plain else ""),
        ]
        return View("access", "SETTINGS // ACCESSIBILITY", items, back=lambda: self.show(self.settings))

    # ---------------------------------------------------------------- webhooks
    def webhooks(self) -> View:
        items = [Line("SEND EVENTS TO DISCORD, NTFY OR ANY URL.", "dim")]
        for h in self.cfg["webhooks"]:
            items.append(Opt(h["name"], lambda h=h: self.show(lambda: self.hook_screen(h)),
                             h["format"] + ("" if h.get("enabled") else " · OFF"), "" if h.get("enabled") else "dim"))
        items.append(Opt("ADD WEBHOOK", self.add_hook))
        return View("hooks", "SETTINGS // WEBHOOKS", items, back=lambda: self.show(self.settings))

    def add_hook(self) -> None:
        back = lambda: self.show(self.webhooks)

        def got_name(name):
            if not name:
                return

            def got_url(url):
                if not url.lower().startswith(("http://", "https://")):
                    self.toast("THE URL MUST START WITH HTTP:// OR HTTPS://")
                    return
                h = webhooks.new_hook(name.upper(), url)
                self.cfg["webhooks"].append(h)
                self.cfg.save()
                self.show(lambda: self.hook_screen(h))
            self.prompt("WEBHOOK // URL", "PASTE OR TYPE THE WEBHOOK URL", got_url, back,
                        hint="DISCORD AND NTFY URLS ARE DETECTED AUTOMATICALLY")
        self.prompt("WEBHOOK // NAME", "A SHORT NAME, FOR EXAMPLE DISCORD STREAM", got_name, back)

    def hook_screen(self, h: dict) -> View:
        back = lambda: self.show(self.webhooks)
        again = lambda: self.show(lambda: self.hook_screen(h), keep_sel=True)

        def save_and(fn):
            def go():
                fn()
                self.cfg.save()
                self.sfx("clack")
                again()
            return go

        def test():
            self.toast("SENDING TEST...")

            def done(r):
                ok = isinstance(r, tuple) and r[0]
                self.sfx("chirp" if ok else "buzz")
                self.toast(("TEST SENT: " if ok else "TEST FAILED: ") + (r[1] if isinstance(r, tuple) else str(r)[:40]))
                self.cfg.save()
                again()
            self.bg(lambda: webhooks.send(h, "test", "test from the terminal", {"test": True}, self.cfg["device_name"]), done)

        def edit_url():
            def got(url):
                if url.lower().startswith(("http://", "https://")):
                    h["url"] = url
                    self.cfg.save()
                    again()
                else:
                    self.toast("THE URL MUST START WITH HTTP:// OR HTTPS://")
            self.prompt("WEBHOOK // URL", "NEW URL", got, again, h["url"])

        def delete():
            self.cfg["webhooks"] = [x for x in self.cfg["webhooks"] if x is not h]
            for t in self.threads:
                if t.get("hook") == h["id"]:
                    t["hook"] = ""
            self.save_threads()
            self.cfg.save()
            back()

        return View("hook", "WEBHOOK // " + h["name"], [
            Line(h["url"], "dim"),
            Line("LAST: " + (h.get("last") or "NEVER SENT"), "dim"), Line(""),
            Opt("ENABLED", save_and(lambda: h.update(enabled=not h.get("enabled"))), "ON" if h.get("enabled") else "OFF"),
            Opt("FORMAT", save_and(lambda: h.update(format=webhooks.FORMATS[(webhooks.FORMATS.index(h["format"]) + 1) % 3])), h["format"]),
            Opt("EVENTS", lambda: self.show(lambda: self.hook_events(h)), f"{len(h['events'])}/{len(webhooks.EVENTS)}"),
            Opt("SEND TEST", test),
            Opt("EDIT URL", edit_url),
            Opt("DELETE WEBHOOK", lambda: self.confirm("CONFIRM", f"DELETE {h['name']}?", "THREADS LINKED TO IT BECOME LOCAL.",
                                                       "YES, DELETE", delete, again), style="bad"),
        ], back=back)

    def hook_events(self, h: dict) -> View:
        def toggle(ev):
            def go():
                if ev in h["events"]:
                    h["events"].remove(ev)
                else:
                    h["events"].append(ev)
                self.cfg.save()
                self.sfx("clack")
                self.show(lambda: self.hook_events(h), keep_sel=True)
            return go
        items = [Line("ENTER TURNS AN EVENT ON OR OFF.", "dim")]
        for ev in webhooks.EVENTS:
            on = ev in h["events"]
            items.append(Opt(("[X] " if on else "[ ] ") + ev, toggle(ev), "", "" if on else "dim"))
        return View("hookev", "WEBHOOK // EVENTS", items, back=lambda: self.show(lambda: self.hook_screen(h)))

    # ---------------------------------------------------------------- firmware
    def firmware(self) -> View:
        prev = self.cfg.get("previous_commit")
        items = [
            Line("INSTALLED: V" + __version__ + (f" ({updater.commit()})" if updater.commit() else "")),
            Line("SOURCE:    " + (updater.remote_url() or "NONE"), "dim"),
            Line("BRANCH:    " + self.cfg["update_branch"].upper(), "dim"), Line(""),
            Opt("CHECK FOR UPDATE", self.check_fw),
            self.cycle("CHECK AT BOOT", "update_check_boot", ["ON", "OFF"], self.firmware),
            Opt("CHANGE BRANCH", lambda: self.prompt("FIRMWARE // BRANCH", "BRANCH TO UPDATE FROM", self.set_branch,
                                                     lambda: self.show(self.firmware), self.cfg["update_branch"])),
        ]
        if prev:
            items.append(Opt("ROLL BACK", lambda: self.confirm("CONFIRM", f"ROLL BACK TO {prev}?", "THE TERMINAL RESTARTS.",
                                                               "YES, ROLL BACK", lambda: self.do_rollback(prev),
                                                               lambda: self.show(self.firmware)), prev, "warn"))
        return View("fw", "SETTINGS // FIRMWARE", items, back=lambda: self.show(self.settings))

    def set_branch(self, b: str) -> None:
        if b:
            self.cfg["update_branch"] = b
            self.cfg.save()
        self.show(self.firmware)

    def check_fw(self) -> None:
        st = {"dots": 0}
        self.show(lambda: View("checking", "FIRMWARE // CHECK", [
            Line("INSTALLED: V" + __version__), Line(""), Line("CONTACTING UPDATE SERVER" + "." * (st["dots"] % 4))],
            footer=("PLEASE WAIT", ""), locked=True, on_enter=lambda: None))
        self.every(0.4, lambda: (st.update(dots=st["dots"] + 1), self.redraw()))

        def done(info):
            self.stop_timers()
            back = lambda: self.show(self.firmware)
            if isinstance(info, Exception) or not info.get("ok"):
                self.sfx("buzz")
                err = str(info) if isinstance(info, Exception) else info["error"]
                self.message("FIRMWARE // CHECK", ["CHECK FAILED.", Line(err.upper(), "dim")], back, "bad")
                return
            if not info["behind"]:
                self.update_info = None
                self.message("FIRMWARE // CHECK", ["YOUR FIRMWARE IS UP TO DATE.", Line(f"V{__version__} · {updater.commit()}", "dim")], back)
                return
            self.update_info = info
            self.sfx("chirp")
            changes = [Line("+ " + c.upper(), "dim") for c in info["changes"]]
            self.show(lambda: View("fwresult", "FIRMWARE // V" + info["version"], [
                Line(f"UPDATE AVAILABLE: V{__version__} -> V{info['version']}", "warn"),
                Line(f"{info['behind']} CHANGE{'S' if info['behind'] != 1 else ''}:", "dim"), *changes, Line(""),
                Opt("INSTALL V" + info["version"], self.install_fw, style="warn"),
                Opt("NOT NOW", back),
            ], back=back))
        self.bg(lambda: updater.check(self.cfg["update_branch"]), done)

    def install_fw(self) -> None:
        phases = ["DOWNLOADING", "VERIFYING", "INSTALLING", "REBOOTING"]
        st = {"ph": 0, "msg": "", "failed": False}

        def screen():
            rows = [Line(("[OK] " if i < st["ph"] else "[..] " if i == st["ph"] else "[  ] ") + p, "dim" if i < st["ph"] else "")
                    for i, p in enumerate(phases)]
            tail = [Line(""), Line("DO NOT POWER OFF THE DEVICE.", "warn")] if not st["failed"] else \
                   [Line(""), Line("FAILED: " + st["msg"], "bad"), Opt("BACK", lambda: self.show(self.firmware))]
            return View("flash", "FIRMWARE // INSTALL", rows + tail, locked=not st["failed"],
                        back=lambda: self.show(self.firmware), footer=("INSTALLING" if not st["failed"] else "", ""))
        self.show(screen)
        branch = self.cfg["update_branch"]

        def work():
            info = updater.check(branch)                       # downloading
            if not info.get("ok"):
                return False, info.get("error", "FETCH FAILED"), ""
            self.ui(lambda: (st.update(ph=1), self.redraw()))
            if updater.dirty():                                 # verifying
                return False, "LOCAL CHANGES FOUND. COMMIT OR DISCARD THEM FIRST.", ""
            time.sleep(0.4)
            self.ui(lambda: (st.update(ph=2), self.redraw()))
            ok, msg, prev = updater.install(branch)             # installing
            if ok:
                self.cfg["previous_commit"] = prev
                self.cfg.save()
                for h in self.cfg["webhooks"]:
                    if h.get("enabled") and "update.installed" in h.get("events", []):
                        webhooks.send(h, "update.installed", f"firmware updated to v{info['version']}",
                                      {"from": prev, "version": info["version"]}, self.cfg["device_name"])
            return ok, msg, prev

        def done(result):
            ok, msg, _ = result if isinstance(result, tuple) else (False, str(result), "")
            if not ok:
                st.update(failed=True, msg=msg.upper())
                self.sfx("buzz")
                self.redraw()
                return
            st["ph"] = 3
            self.redraw()
            self.later(1.2, lambda: self.exit("restart"))
        self.bg(work, done)

    def do_rollback(self, prev: str) -> None:
        ok, msg = updater.rollback(prev)
        if ok:
            self.cfg["previous_commit"] = ""
            self.cfg.save()
            self.exit("restart")
        else:
            self.message("FIRMWARE", ["ROLL BACK FAILED.", Line(msg.upper(), "dim")], lambda: self.show(self.firmware), "bad")

    # ---------------------------------------------------------------- about / power
    def about(self) -> View:
        rows = [Line(f"4RDEN INDUSTRIES {self.cfg['device_name']}"), Line("")]
        for k, v in system.sysinfo():
            rows.append(Line(f"{k:<10} {v}"))
        rows += [Line(f"{'FIRMWARE':<10} V{__version__} {updater.commit()}"),
                 Line(f"{'MIC':<10} {'YES' if self.mic_ok else 'NONE'}"), Line(""),
                 Line("CONFIG " + str(storage.Config.path), "dim"), Line("DATA   " + str(storage.DATA_DIR), "dim")]
        return View("about", "SETTINGS // ABOUT", rows, back=lambda: self.show(self.settings), on_enter=lambda: None)

    def power(self) -> View:
        items = [Line("POWER OPTIONS:", "dim")]
        if system.IS_LINUX and system.have("systemctl"):
            items.append(Opt("SHUT DOWN DEVICE", lambda: self.confirm("CONFIRM", "SHUT DOWN THE DEVICE?", "UNSAVED WORK IS LOST.",
                                                                      "YES, SHUT DOWN", lambda: self.do_power("poweroff"),
                                                                      lambda: self.show(self.power)), style="warn"))
            items.append(Opt("REBOOT DEVICE", lambda: self.do_power("reboot")))
        items.append(Opt("RESTART TERMINAL", lambda: self.exit("restart")))
        items.append(Opt("EXIT TO SHELL", lambda: self.exit("shell")))
        return View("power", "POWER", items)

    def do_power(self, action: str) -> None:
        for d in self.drives:
            if d.mountpoint:
                system.unmount(d)
        self.toast("GOODBYE.")
        ok, out = system.power(action)
        if not ok:
            self.toast("FAILED: " + (out.splitlines()[-1][:50] if out else "?"), 8)
