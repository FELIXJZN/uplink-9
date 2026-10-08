"""Entry point: python3 -m uplink [--plain] [--no-boot]"""
from __future__ import annotations

import argparse
import curses
import os
import sys

from . import __version__, app, config, system, updater


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="uplink", description="UPLINK-9 terminal")
    parser.add_argument("--plain", action="store_true",
                        help="accessibility mode: no colour or effects (not saved)")
    parser.add_argument("--no-boot", action="store_true", help="skip the boot sequence")
    parser.add_argument("--version", action="version", version=f"UPLINK-9 {__version__}")
    args = parser.parse_args(argv)

    if not sys.stdin.isatty():
        print("UPLINK-9 needs a real terminal to run.", file=sys.stderr)
        return 1

    os.environ.setdefault("ESCDELAY", "25")  # make ESC react instantly
    cfg = config.load()
    if args.plain:
        cfg["_cli_plain"] = True
    try:
        curses.wrapper(app.run, cfg, args.no_boot)
    except system.Restart:
        os.chdir(updater.REPO_DIR)
        new_args = [a for a in sys.argv[1:] if a != "--no-boot"] + ["--no-boot"]
        os.execv(sys.executable, [sys.executable, "-m", "uplink", *new_args])
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
