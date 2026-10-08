"""Boot sequence and main menu."""
from __future__ import annotations

from . import __version__, holotapes, messages, system, updater, usb, webhooks
from .ui import Screen

SECTIONS = [
    ("HOLOTAPES", holotapes.run),
    ("MESSAGES", messages.run),
    ("USB DRIVES", usb.run),
    ("WEBHOOKS", webhooks.run),
    ("SYSTEM", system.run),
]


def short_status(status: updater.Status) -> str:
    """A few words that fit on a narrow handheld screen."""
    if not status.ok:
        return "FAILED"
    if status.available:
        return "AVAILABLE"
    if "NO RELEASES" in status.message:
        return "NO RELEASES"
    if "LOCAL" in status.message:
        return "LOCAL CHANGES"
    return "UP TO DATE"


def boot(scr: Screen, cfg: dict, ctx: dict) -> None:
    animate = scr.effect("boot_sequence")
    scr.frame("BOOT")
    if animate:
        scr.flicker(3)
        scr.frame("BOOT")
    row = 2

    def line(text, attr=None, wait=0.08):
        nonlocal row
        scr.type_text(row, 1, text, attr)
        scr.pause(wait)
        row += 1

    line(f"{cfg.get('callsign', 'UPLINK-9')} TERMINAL  v{__version__}", scr.bright)
    line("4RDEN SYSTEMS // FIELD UNIT")
    row += 1
    mem = system.mem_total_mb()
    line(f"{'MEMORY CHECK ':.<22} {str(mem) + ' MB' if mem else 'OK'}")
    drives = usb.mounted_drives(cfg.get("usb", {}).get("mount_roots", []))
    line(f"{'USB BUS ':.<22} {len(drives)} DRIVE(S)")
    line(f"{'NETWORK ':.<22} {system.local_ip() or 'OFFLINE'}")
    line(f"{'UPDATE CHANNEL ':.<22} {cfg.get('update', {}).get('channel', 'tags').upper()}")

    if cfg.get("update", {}).get("check_on_boot", True) and system.local_ip():
        scr.put(row, 1, f"{'CHECKING UPDATES ':.<22} ...")
        scr.s.refresh()
        status = updater.check(cfg, fetch_timeout=8)
        ctx["update"] = status
        scr.put(row, 1, " " * 40)
        line(f"{'CHECKING UPDATES ':.<22} {short_status(status)}")

    if cfg.get("_error"):
        line(f"WARNING: {cfg['_error']}", scr.bright)
    row += 1
    line("READY.", scr.bright, wait=0.4)
    scr.skip_effects = False


def main_menu(scr: Screen, cfg: dict, ctx: dict) -> None:
    sel = 0
    while True:
        names = [name for name, _ in SECTIONS]
        status = ctx.get("update")
        if status and status.available:
            names[-1] = "SYSTEM  (UPDATE READY)"
        choice = scr.menu("MAIN", names, hint="1-5 pick  j/k move  q exit", start=sel)
        if choice is None:
            if scr.confirm("EXIT", "Leave the terminal and drop to the Linux shell?"):
                return
            continue
        sel = choice
        SECTIONS[choice][1](scr, cfg, ctx)


def run(stdscr, cfg: dict, no_boot: bool = False) -> None:
    scr = Screen(stdscr, cfg)
    ctx: dict = {"update": None}
    if not no_boot:
        boot(scr, cfg, ctx)
    try:
        main_menu(scr, cfg, ctx)
    except system.ExitToShell:
        return
