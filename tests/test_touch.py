"""Graphics/touch mode, touchscreen detection, the release channel and carrying over v0.2 data.
The screen tests run headless (SDL's dummy driver) with simulated finger taps; they're skipped without pygame."""
import json
import os
import time
import wave

import pytest

from uplink import storage, touch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

DEVICES = """\
I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="Goodix Capacitive TouchScreen"
H: Handlers=mouse0 event1
B: PROP=2
B: EV=b
B: KEY=400 0 0 0 0 0
B: ABS=2658000 3

I: Bus=0018 Vendor=06cb Product=7e7e Version=0100
N: Name="SYNA2B31:00 06CB:7E7E Touchpad"
H: Handlers=mouse1 event2
B: PROP=5
B: EV=1b
B: ABS=2e0800000000003

I: Bus=0011 Vendor=0001 Product=0001 Version=ab41
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: PROP=0
B: EV=120013
"""


# ---------------------------------------------------------------- touchscreen detection
def test_finds_only_the_touchscreen():
    found = [d["name"] for d in touch.parse_devices(DEVICES) if touch.is_touchscreen(d, 64)]
    assert found == ["Goodix Capacitive TouchScreen"]       # the touchpad and keyboard are left out


def test_detect_without_the_device_list():
    assert touch.detect("/nonexistent") == []


def test_cli_detect(capsys, home):
    from uplink.__main__ import main
    assert main(["--detect", "--tty", "--touch"]) == 0
    out = capsys.readouterr().out
    assert "interface:    text" in out and "touch mode:   on" in out


# ---------------------------------------------------------------- touch buttons from footers
def test_footer_buttons():
    pytest.importorskip("pygame")
    from uplink.engine import View
    from uplink.gui import footer_buttons
    v = View("x", "X", footer=("[ENTER] PAUSE", "[ESC] EJECT"))
    assert footer_buttons(v, False) == [("PAUSE", "enter"), ("EJECT", "escape")]
    v = View("x", "X", footer=("LINE 1/9", "[▲▼] SCROLL [ESC] BACK"))
    assert footer_buttons(v, False) == [("▲", "up"), ("▼", "down"), ("BACK", "escape")]
    v = View("x", "X", footer=("", "[ENTER] SELECT"), back=lambda: None)      # main menu: options are tapped
    assert footer_buttons(v, False) == []
    v = View("x", "X", footer=("", ""), locked=True)                           # firmware flashing: no way out
    assert footer_buttons(v, False) == []


# ---------------------------------------------------------------- the touch screen itself
@pytest.fixture
def touch_app(home):
    pygame = pytest.importorskip("pygame")
    from uplink import gui
    app = gui.make_touch_app(no_boot=True, touch=True)
    app.cfg["sounds"] = "OFF"
    app.open_display()
    app.core_start()

    def run(sec=0.3):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.pump(0.02)

    def tap(pos):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos, touch=True))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos, touch=True))
        run()

    def tap_option(word):
        for row, o in app.row_map.items():
            if word in app.view.opts[o].label.upper():
                return tap((app._grid.x + 30, app._grid.y + row * app.pitch + app.pitch // 2))
        raise AssertionError(f"no option {word}: {[o.label for o in app.view.opts]}")

    def tap_button(label):
        for rect, text, _ in app._buttons + app._keys:
            if text == label:
                return tap(rect.center)
        raise AssertionError(f"no button {label}: {[b[1] for b in app._buttons + app._keys]}")

    app.t_run, app.t_tap, app.t_option, app.t_button = run, tap, tap_option, tap_button
    run()
    yield app
    app.exit()
    app.core_stop()
    pygame.quit()


def test_touch_only_walkthrough(touch_app):
    app = touch_app
    assert app.view.id == "login"
    app.t_option("USER")
    assert app.view.id == "main" and app.role == "USER"
    # a tape plays, pauses from its button, ejects from its button
    app.t_option("HOLOTAPE")
    app.t_option("BUILD LOG")
    app.t_option("PLAY")
    assert app.view.id == "tape"
    app.t_button("PAUSE")
    app.t_button("EJECT")
    assert app.view.id == "tapemenu"
    # BACK button, then a message typed on the on-screen keyboard
    app.t_button("BACK")
    app.t_button("BACK")
    app.t_option("MESSAGES")
    app.t_option("NOTES")
    app.t_option("WRITE")
    assert app._keys, "the on-screen keyboard should be up"
    app.t_button("Aa")
    app.t_button("H")                 # shift is one-shot
    app.t_button("i")
    app.t_button("SEND")
    assert app.view.id == "thread"
    assert app.threads[0]["msgs"][-1]["t"] == "Hi"
    assert not app._keys


def test_swipe_scrolls(touch_app):
    import pygame
    app = touch_app
    app.t_option("ADMIN")
    if app.view.id != "main":        # no password set yet: the admin login asks to make one
        app.show(app.main)
        app.t_run()
    start = app.sel
    x, y = app._grid.centerx, app._grid.bottom - 10
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x, y), touch=True))
    for dy in range(0, 3 * app.pitch + 5, 8):
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(x, y - dy), rel=(0, -8), buttons=(1, 0, 0), touch=True))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x, y - 3 * app.pitch), touch=True))
    app.t_run()
    assert app.sel == start + 3 and app.view.id == "main"     # a swipe scrolls; it never counts as a tap


def test_first_touch_turns_touch_mode_on(home):
    pygame = pytest.importorskip("pygame")
    from uplink import gui
    app = gui.make_touch_app(no_boot=True, touch=False)
    app.cfg["sounds"] = "OFF"
    app.open_display()
    app.core_start()
    app.pump(0.05)
    cols = app.screen_size()[0]
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5), touch=True))
    app.pump(0.05)
    assert app.touch and app.screen_size()[0] < cols        # bigger text and targets
    app.exit()
    app.core_stop()
    pygame.quit()


# ---------------------------------------------------------------- release channel
def git(*args, cwd):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def test_version_order():
    from uplink.updater import parse_version
    assert parse_version("v0.2.0") < parse_version("0.11-beta") < parse_version("v0.12-beta") < parse_version("0.12")


def test_release_channel(tmp_path, monkeypatch):
    from uplink import updater
    origin, dev, device = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "device"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    dev.mkdir()
    (dev / "VERSION").write_text("0.11-beta\n")
    (dev / "requirements.txt").write_text("")
    git("init", "-q", "-b", "main", cwd=dev)
    git("add", "-A", cwd=dev)
    git("commit", "-qm", "first", cwd=dev)
    git("remote", "add", "origin", str(origin), cwd=dev)
    git("push", "-q", "origin", "main", cwd=dev)
    git("clone", "-q", str(origin), str(device), cwd=tmp_path)
    monkeypatch.setattr(updater, "APP_DIR", device)

    assert updater.check(channel="RELEASES")["note"] == "NO RELEASES PUBLISHED YET"
    (dev / "VERSION").write_text("0.12-beta\n")
    git("commit", "-qam", "Touch screen", cwd=dev)
    git("push", "-q", "origin", "main", cwd=dev)
    assert updater.check(channel="RELEASES")["behind"] == 0         # pushed but not released
    assert updater.check("main", "BRANCH")["behind"] == 1           # the branch channel sees it
    git("tag", "v0.12-beta", cwd=dev)
    git("tag", "v0.9", "HEAD~1", cwd=dev)                             # an older release is never offered
    git("push", "-q", "origin", "--tags", cwd=dev)
    info = updater.check(channel="RELEASES")
    assert info["behind"] == 1 and info["version"] == "0.12-beta" and info["target"] == "v0.12-beta"
    ok, _, _ = updater.install("main", info["target"])
    assert ok and updater.local_version() == "0.12-beta"
    assert updater.check(channel="RELEASES")["behind"] == 0


# ---------------------------------------------------------------- carrying over v0.2
def write_wav(path, secs=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * secs)


def test_v02_settings_and_tapes_carry_over(home):
    storage.Config.path.parent.mkdir(parents=True, exist_ok=True)
    storage.Config.path.write_text(json.dumps({
        "callsign": "felix-unit", "interface": "gui", "touch": True, "plain_mode": True,
        "gui": {"fullscreen": "auto", "window": [800, 480], "font_size": 0},
        "effects": {"typing": False, "scanlines": False}, "update": {"channel": "tags", "branch": "main"},
        "webhooks": [{"name": "discord", "url": "https://discord.com/api/webhooks/1/x", "format": "discord"}],
    }))
    old = storage.DATA_DIR / "holotapes"
    old.mkdir(parents=True)
    (old / "a.json").write_text(json.dumps({"id": "a", "title": "rack notes", "created": "2026-10-08T14:00:00",
                                            "text": "line one\nline two", "audio": None}))
    write_wav(old / "b.wav")
    (old / "b.json").write_text(json.dumps({"id": "b", "title": "voice", "created": "2026-10-08T14:05:00",
                                            "text": "", "audio": "b.wav"}))
    cfg = storage.Config()
    assert cfg["device_name"] == "FELIX-UNIT" and cfg["interface"] == "GRAPHICS" and cfg["touch"] == "ON"
    assert cfg["plain"] == "ON" and cfg["animations"] == "OFF" and cfg["scanlines"] == "OFF"
    assert cfg["update_channel"] == "RELEASES"
    assert cfg["webhooks"][0]["format"] == "DISCORD"
    assert "callsign" not in json.loads(storage.Config.path.read_text())
    assert any("V0.2" in p for p in storage.LOAD_PROBLEMS)
    tapes = {t["name"]: t for t in storage.load_tapes()}
    assert tapes["RACK NOTES"]["lines"] == ["line one", "line two"]
    assert tapes["VOICE"]["secs"] == 2 and tapes["VOICE"]["audio"].endswith("b.wav")
    assert len(storage.load_tapes()) == 2                            # imported once, not every start


def test_usb_tape_import(home, tmp_path):
    drive = tmp_path / "stick"
    (drive / "UPLINK_TAPES").mkdir(parents=True)
    (drive / "UPLINK_TAPES" / "FIELD LOG 01.txt").write_text("hello\nworld\n")
    write_wav(drive / "UPLINK_TAPES" / "FIELD LOG 01.wav", 3)
    (drive / "UPLINK-9" / "holotapes").mkdir(parents=True)
    (drive / "UPLINK-9" / "holotapes" / "z.json").write_text(json.dumps({"id": "z", "title": "from v0.2", "text": "x"}))
    assert storage.import_usb_tapes(drive) == 2
    assert storage.import_usb_tapes(drive) == 0                      # already here
    tapes = {t["name"]: t for t in storage.load_tapes()}
    assert tapes["FIELD LOG 01"]["secs"] == 3 and tapes["FIELD LOG 01"]["lines"] == ["hello", "world"]
    assert "FROM V0.2" in tapes
