"""Entry point: python3 -m uplink [--plain] [--no-boot] [--gui | --tty] [--touch | --no-touch]"""
from __future__ import annotations

import argparse
import os
import re
import sys

from . import __version__, app, config, system, touch, updater


def choose_interface(pref: str) -> str:
    """'gui' on the device's own screen or a desktop, 'tty' over SSH."""
    if pref in ("gui", "tty"):
        return pref
    if sys.platform == "win32" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return "gui"
    try:
        tty = os.ttyname(0)
    except OSError:
        tty = ""
    if re.fullmatch(r"/dev/tty\d+", tty) or tty == "/dev/console":
        return "gui"  # the device's own console: draw straight to the screen
    return "tty"


def resolve_touch(setting) -> tuple[bool, list[str]]:
    found = touch.detect()
    if setting in (True, False):
        return setting, found
    return bool(found), found


def try_gui(cfg: dict, no_boot: bool, use_touch: bool) -> str | None:
    """Run the graphical interface. Returns None when it ran, else why it couldn't."""
    try:
        from . import gui
    except ImportError:
        return "pygame missing (sudo apt install python3-pygame)"
    try:
        surface, fullscreen, driver = gui.open_display(cfg)
    except gui.DisplayUnavailable as exc:
        return f"no display ({exc})"
    try:
        scr = gui.GuiScreen(surface, cfg, touch=use_touch, fullscreen=fullscreen, driver=driver)
        app.start(scr, cfg, no_boot)
    finally:
        gui.pygame.quit()
    return None


def run_tty(cfg: dict, no_boot: bool) -> None:
    import curses

    from .ui import Screen

    os.environ.setdefault("ESCDELAY", "25")  # make ESC react instantly
    curses.wrapper(lambda stdscr: app.start(Screen(stdscr, cfg), cfg, no_boot))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="uplink", description="UPLINK-9 terminal")
    parser.add_argument("--plain", action="store_true",
                        help="accessibility mode: no colour or effects (not saved)")
    parser.add_argument("--no-boot", action="store_true", help="skip the boot sequence")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--gui", dest="interface", action="store_const", const="gui",
                    help="graphical screen (touch capable)")
    ui.add_argument("--tty", dest="interface", action="store_const", const="tty",
                    help="text console only")
    tch = parser.add_mutually_exclusive_group()
    tch.add_argument("--touch", dest="touch", action="store_const", const=True)
    tch.add_argument("--no-touch", dest="touch", action="store_const", const=False)
    parser.add_argument("--detect", action="store_true",
                        help="print what input/display UPLINK would use and exit")
    parser.add_argument("--version", action="version", version=f"UPLINK-9 {__version__}")
    args = parser.parse_args(argv)

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    cfg = config.load()
    if args.plain:
        cfg["_cli_plain"] = True
    interface = choose_interface(args.interface or cfg.get("interface", "auto"))
    use_touch, found = resolve_touch(cfg.get("touch", "auto") if args.touch is None else args.touch)

    if args.detect:
        print(f"interface:    {interface}")
        print(f"touchscreen:  {', '.join(found) if found else 'none found'}")
        print(f"touch mode:   {'on' if use_touch else 'off'}")
        return 0

    try:
        if interface == "gui":
            problem = try_gui(cfg, args.no_boot, use_touch)
            if problem is None:
                return 0
            if (args.interface or cfg.get("interface")) == "gui":
                print(f"UPLINK-9: graphical mode unavailable: {problem}", file=sys.stderr)
                return 1
            cfg["_notice"] = f"TEXT MODE: {problem}"
        if not sys.stdin.isatty():
            print("UPLINK-9 needs a screen or a terminal to run.", file=sys.stderr)
            return 1
        run_tty(cfg, args.no_boot)
    except system.Restart:
        os.chdir(updater.REPO_DIR)
        new_args = [a for a in sys.argv[1:] if a != "--no-boot"] + ["--no-boot"]
        os.execv(sys.executable, [sys.executable, "-m", "uplink", *new_args])
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
