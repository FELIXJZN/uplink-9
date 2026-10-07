"""End-to-end tests: the real app, driven by simulated key presses in a headless terminal."""
import asyncio
import http.server
import json
import threading
import time

from uplink.app import Uplink
from uplink.engine import Opt, View


def run(test, size=(64, 30)):
    """Start the app headless, skip the boot animation, then run test(app, pilot)."""
    async def main():
        app = Uplink()
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.3)
            await pilot.press("enter")          # skip boot
            await pilot.pause(0.3)
            await test(app, pilot)
        return app
    return asyncio.run(main())


async def pick(app, pilot, label):
    """Select the option with this label and press ENTER."""
    labels = [o.label for o in app.view.opts]
    assert label in labels, f"{label!r} not in {labels}"
    app.sel = labels.index(label)
    await pilot.press("enter")
    await pilot.pause(0.15)


async def type_text(pilot, text):
    for c in text:
        await pilot.press("space" if c == " " else c)


def test_main_menu_and_every_screen_opens(home):
    async def t(app, pilot):
        assert app.view.id == "main"
        for name in ["FILES", "USB DRIVES", "MESSAGES", "NODES", "VPN", "HOLOTAPE", "SETTINGS", "POWER"]:
            await pick(app, pilot, name)
            await pilot.pause(0.3)
            assert app.view.id not in ("main", "error"), name
            await pilot.press("escape")
            await pilot.pause(0.1)
            assert app.view.id == "main"
    run(t)


def test_boot_skip_race(home):
    """ENTER before the boot checks finish must not replay the boot over the main menu."""
    async def main():
        app = Uplink()
        async with app.run_test(size=(64, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause(2.0)                # boot checks finish meanwhile
            assert app.view.id == "main"
    asyncio.run(main())


def test_copy_view_and_note(home):
    notes = home / "notes"
    notes.mkdir()
    (notes / "hello.txt").write_text("hello\n" + "x" * 500 + "\nlast line\n")

    async def t(app, pilot):
        await pick(app, pilot, "FILES")
        await pick(app, pilot, "HOME")
        await pick(app, pilot, "notes/")
        await pick(app, pilot, "hello.txt")
        await pick(app, pilot, "VIEW")
        assert app.view.id == "viewer"
        shown = "".join(i.text for i in app.view.items)
        assert "last line" in shown, "long lines must wrap without pushing text off screen"
        await pilot.press("escape")
        await pick(app, pilot, "COPY TO...")
        await pick(app, pilot, "HOME")
        await pick(app, pilot, "[ COPY HERE ]")
        await pilot.pause(0.6)
        assert (home / "hello.txt").read_text() == (notes / "hello.txt").read_text()
        await pilot.press("escape")
        # empty note: nothing written
        await pick(app, pilot, "[ NEW NOTE ]")
        await type_text(pilot, "empty")
        await pilot.press("enter")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not (home / "empty.txt").exists()
        # real note
        await pick(app, pilot, "[ NEW NOTE ]")
        await type_text(pilot, "log1")
        await pilot.press("enter")
        await type_text(pilot, "first line")
        await pilot.press("enter")
        await type_text(pilot, "second")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert (home / "log1.txt").read_text() == "first line\nsecond\n"
    run(t)


def test_folder_cannot_go_into_itself(home):
    (home / "box" / "inner").mkdir(parents=True)

    async def t(app, pilot):
        await pick(app, pilot, "FILES")
        await pick(app, pilot, "HOME")
        await pick(app, pilot, "box/")
        await pick(app, pilot, "[ THIS FOLDER... ]")
        await pick(app, pilot, "COPY TO...")
        await pick(app, pilot, "HOME")
        await pick(app, pilot, "box/")
        await pick(app, pilot, "[ COPY HERE ]")
        assert "INSIDE ITSELF" in " ".join(getattr(i, "text", "") for i in app.view.items)
    run(t)


def test_tape_record_and_play(home):
    async def t(app, pilot):
        await pick(app, pilot, "HOLOTAPE")
        await pick(app, pilot, "BUILD LOG 01")
        await pick(app, pilot, "PLAY")
        await pilot.pause(1.0)
        assert app.view.id == "tape"
        await pilot.press("escape")
        await pilot.press("escape")
        await pick(app, pilot, "RECORD NEW TAPE")
        await type_text(pilot, "test log")
        await pilot.press("enter")
        await pilot.press("enter")              # empty line stops and saves
        await pilot.pause(0.3)
        assert app.view.id == "saved"
        assert [x["name"] for x in app.user_tapes] == ["FIELD LOG 01"]
        assert app.user_tapes[0]["lines"] == ["test log"]
    run(t)


def test_plain_mode_turns_effects_off(home):
    async def t(app, pilot):
        app.cfg["color"] = "AMBER"
        await pick(app, pilot, "SETTINGS")
        await pick(app, pilot, "ACCESSIBILITY")
        await pick(app, pilot, "PLAIN MODE (REALISM)")
        assert app.cfg["plain"] == "ON"
        assert app.pal[0] == "#3dff7a", "plain mode is always green"
        assert not app.fx("sounds") and not app.fx("animations") and not app.fx("cursor_blink")
    run(t)


def test_webhook_add_and_test(home):
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/hook"

    async def t(app, pilot):
        await pick(app, pilot, "SETTINGS")
        await pick(app, pilot, "WEBHOOKS")
        await pick(app, pilot, "ADD WEBHOOK")
        await type_text(pilot, "local")
        await pilot.press("enter")
        await type_text(pilot, url)
        await pilot.press("enter")
        assert app.view.id == "hook"
        await pick(app, pilot, "SEND TEST")
        for _ in range(30):
            await pilot.pause(0.1)
            if got:
                break
        assert got and got[0]["event"] == "test"
        assert app.cfg["webhooks"][0]["last"].startswith("OK")
    run(t)
    srv.shutdown()


def test_error_screen_instead_of_crash(home):
    async def t(app, pilot):
        def broken():
            raise ValueError("boom")
        app.show(broken)
        await pilot.pause(0.1)
        assert app.view.id == "error"
        await pick(app, pilot, "MAIN MENU")
        assert app.view.id == "main"
        from uplink.engine import CRASH_LOG
        assert "boom" in CRASH_LOG.read_text()
    run(t)


def test_render_speed(home):
    """Rendering must stay cheap: the Pi redraws up to 40 times a second during animations."""
    for i in range(500):
        (home / f"file{i:03d}.wav").write_bytes(b"x")

    async def t(app, pilot):
        from pathlib import Path
        app.open_dir(Path(home))
        await pilot.pause(0.1)
        n = 50
        start = time.perf_counter()
        for _ in range(n):
            app.redraw()
        rebuild_ms = (time.perf_counter() - start) / n * 1000
        start = time.perf_counter()
        for i in range(n):
            app._ul_sig = None
            app.render_view()
        render_ms = (time.perf_counter() - start) / n * 1000
        print(f"\n500-file folder: rebuild {rebuild_ms:.1f} ms, render {render_ms:.1f} ms")
        assert rebuild_ms < 50 and render_ms < 30
    run(t)
