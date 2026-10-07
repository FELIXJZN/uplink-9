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
        app.cfg["login_at_boot"] = "OFF"       # these tests start as admin; login has its own tests
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
        app.cfg["login_at_boot"] = "OFF"
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


# ------------------------------------------------------------------ login and roles
def run_login(test, admin_pw=""):
    """Start with login at boot on (the default)."""
    async def main():
        from uplink import auth
        app = Uplink()
        app.cfg["login_at_boot"] = "ON"
        app.cfg["admin_pw"] = auth.hash_password(admin_pw) if admin_pw else ""
        async with app.run_test(size=(64, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert app.view.id == "login"
            await test(app, pilot)
    asyncio.run(main())


def test_first_admin_login_sets_password(home):
    async def t(app, pilot):
        await pick(app, pilot, "ADMIN")
        await type_text(pilot, "rack42")
        await pilot.press("enter")
        await type_text(pilot, "rack42")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.view.id == "main" and app.role == "ADMIN"
        assert app.cfg["admin_pw"].startswith("pbkdf2$") and "rack42" not in app.cfg["admin_pw"]
    run_login(t)


def test_wrong_password_locks_terminal(home):
    async def t(app, pilot):
        await pick(app, pilot, "ADMIN")
        for attempt in range(3):
            assert app.view.id == "prompt"          # a wrong password asks again
            await type_text(pilot, "nope")
            await pilot.press("enter")
            await pilot.pause(0.2)
        assert app.view.id == "lockout"
        await pilot.press("escape")
        assert app.view.id == "lockout", "ESC must not escape the lockout"
    run_login(t, admin_pw="right")


def test_right_password_and_masking(home):
    async def t(app, pilot):
        await pick(app, pilot, "ADMIN")
        await type_text(pilot, "secret")
        assert "secret" not in str(app.term.render()), "password must be masked on screen"
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.view.id == "main" and app.role == "ADMIN"
    run_login(t, admin_pw="secret")


def test_user_is_restricted(home):
    async def t(app, pilot):
        await pick(app, pilot, "USER")
        assert app.role == "USER"
        await pick(app, pilot, "SETTINGS")
        await pick(app, pilot, "WEBHOOKS")
        assert app.view.id == "settings", "a user must not open webhooks"
        await pilot.press("escape")
        await pick(app, pilot, "POWER")
        await pick(app, pilot, "EXIT TO SHELL")
        assert app.is_running, "a user must not exit to the shell"
        app.action_quit()
        await pilot.pause(0.1)
        assert app.is_running, "Ctrl+Q must not exit for a user"
        assert all(name != "SYSTEM /" for name, _ in app.roots())
        await pick(app, pilot, "LOG OUT")
        assert app.view.id == "login"
    run_login(t, admin_pw="x1y2")


def test_coming_soon_shows_qr(home):
    async def t(app, pilot):
        await pick(app, pilot, "CLASSIFIED")
        assert app.view.id == "soon"
        await pick(app, pilot, "SHOW QR CODE")
        text = "\n".join(i.text for i in app.view.items)
        assert "█" in text and "discord.gg" in text
        await pilot.press("escape")
        await pilot.press("escape")
        assert app.view.id == "login"
    run_login(t)


def test_aspect_ratio_letterboxes(home):
    async def t(app, pilot):
        app.cfg["aspect"] = "16:9"
        app._ul_sig = None
        app.render_view()
        assert app.pad_top > 0
        await pick(app, pilot, "FILES")      # clicks still land on the right rows when letterboxed
        assert app.view.id == "roots"
    run(t)


def test_field_unit(home):
    async def t(app, pilot):
        await pick(app, pilot, "FIELD UNIT")
        assert app.view.id == "field" and app.role == "USER"
        text = lambda: "\n".join(getattr(i, "text", getattr(i, "label", "")) for i in app.view.items)
        assert "[VITALS]" in text() and "CPU LOAD" in text() and "CONDITION" in text()
        await pilot.pause(1.2)
        assert len(app._ul_field["hist"]) >= 2, "vitals keep sampling every second"
        await pilot.press("right")
        assert "[CARGO]" in text()
        await pilot.press("right")
        assert "[LOGS]" in text() and "BUILD LOG 01" in text()
        await pick(app, pilot, "BUILD LOG 01")
        assert app.view.id == "tape"
        await pilot.press("escape")
        assert app.view.id == "field" and "[LOGS]" in text(), "ejecting a tape returns to the Field Unit"
        await pilot.press("left")
        await pilot.press("left")
        await pilot.press("left")
        assert "[SIGNAL]" in text() and "PVE-1" in text()
        await pilot.press("escape")
        assert app.view.id == "login"
    run_login(t)
