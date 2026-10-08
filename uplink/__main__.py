"""Start the terminal:  python -m uplink  [--gui | --tty] [--touch | --no-touch] [--plain] [--no-boot] [--detect]"""
from __future__ import annotations

import argparse
import os
import re
import sys

from . import __version__, touch, updater, version_label


def on_device_console() -> bool:
    """True on the device's own screen (a Linux virtual console), not over SSH or in a desktop terminal."""
    if sys.platform == "win32" or os.environ.get("SSH_CONNECTION"):
        return False
    try:
        tty = os.ttyname(0)
    except OSError:
        return False
    return bool(re.fullmatch(r"/dev/tty\d+", tty)) or tty == "/dev/console"


def choose_interface(pref: str) -> str:
    """'gui' or 'tty'. AUTO picks graphics on the device's own console when pygame is installed."""
    pref = (pref or "AUTO").upper()
    if pref in ("GRAPHICS", "GUI"):
        return "gui"
    if pref in ("TEXT", "TTY"):
        return "tty"
    if on_device_console():
        try:
            import pygame  # noqa: F401
            return "gui"
        except ImportError:
            return "tty"
    return "tty"


def resolve_touch(setting) -> tuple[bool, list[str]]:
    found = touch.detect()
    setting = str(setting).upper()
    if setting in ("ON", "TRUE"):
        return True, found
    if setting in ("OFF", "FALSE"):
        return False, found
    return bool(found), found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="uplink", description="Uplink-9 terminal")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--gui", dest="interface", action="store_const", const="GRAPHICS",
                    help="graphics mode (pygame): the device's display, with touch")
    ui.add_argument("--tty", dest="interface", action="store_const", const="TEXT", help="text mode (any terminal)")
    tch = parser.add_mutually_exclusive_group()
    tch.add_argument("--touch", dest="touch", action="store_const", const="ON", help="touch controls on")
    tch.add_argument("--no-touch", dest="touch", action="store_const", const="OFF", help="touch controls off")
    parser.add_argument("--plain", action="store_true", help="plain mode for this session (not saved)")
    parser.add_argument("--no-boot", action="store_true", help="skip the boot sequence")
    parser.add_argument("--detect", action="store_true", help="show which screen and touch mode would be used, then exit")
    parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"Uplink-9 {version_label(__version__)}")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    from .storage import Config
    cfg = Config()
    interface = choose_interface(args.interface or cfg["interface"])
    touch_setting = args.touch or cfg["touch"]
    use_touch, found = resolve_touch(touch_setting)

    if args.detect:
        print(f"interface:    {'graphics' if interface == 'gui' else 'text'}")
        print(f"touchscreen:  {', '.join(found) if found else 'none found'}")
        print(f"touch mode:   {'on' if use_touch else 'off'}" + (" (switches on at the first touch)" if touch_setting == "AUTO" and not use_touch else ""))
        return 0

    no_boot = args.no_boot or args.after_update
    app = None
    notice = ""
    if interface == "gui":
        try:
            from . import gui
            app = gui.make_touch_app(after_update=args.after_update, no_boot=no_boot,
                                     touch=use_touch, touch_setting=touch_setting)
            app.force_plain = args.plain
            result = app.run()
        except ImportError:
            notice = "GRAPHICS MODE NEEDS PYGAME (sudo apt install python3-pygame)"
        except Exception as e:  # noqa: BLE001 - no display: fall back to text mode
            if type(e).__name__ != "DisplayUnavailable":
                raise
            notice = f"NO DISPLAY FOR GRAPHICS MODE ({e})"
        if notice:
            if (args.interface or cfg["interface"]) == "GRAPHICS":
                print("Uplink-9: " + notice.lower(), file=sys.stderr)
                return 1
            app = None
    if app is None:
        from . import engine
        if engine.App is None:
            print("Uplink-9: text mode needs Textual. Run ./install.sh in the uplink-9 folder." +
                  (" (" + notice.lower() + ")" if notice else ""), file=sys.stderr)
            return 1
        from .app import Uplink
        app = Uplink(after_update=args.after_update, no_boot=no_boot)
        app.force_plain = args.plain
        if notice:
            app.boot_notice = notice
        result = app.run()
    if result == "restart":
        updater.restart()          # replaces this process
    # a crash gives a non-zero code, so the launcher knows to restart instead of dropping to a shell
    return app.return_code or 0


if __name__ == "__main__":
    sys.exit(main())
