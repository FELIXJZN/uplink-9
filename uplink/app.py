"""Boot sequence and main menu (works on either screen backend)."""
from __future__ import annotations

from . import __version__, holotapes, messages, system, updater, usb, webhooks
from .text import leader

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


def boot(scr, cfg: dict, ctx: dict) -> None:
    scr.frame("BOOT", back=False)
    if scr.effect("boot_sequence"):
        scr.flicker(3)
        scr.frame("BOOT", back=False)
    rows, cols = scr.size()
    row = 2 if not scr.touch else 3

    def line(text, attr=None, wait=0.08):
        nonlocal row
        scr.type_text(row, 1, text, attr)
        scr.pause(wait)
        row += 1

    line(f"{cfg.get('callsign', 'UPLINK-9')} TERMINAL  v{__version__}", scr.bright)
    line("4RDEN SYSTEMS // FIELD UNIT")
    row += 1
    mem = system.mem_total_mb()
    line(leader("MEMORY", cols) + (f"{mem} MB" if mem else "OK"))
    line(leader("DISPLAY", cols) + scr.describe())
    drives = usb.mounted_drives(cfg.get("usb", {}).get("mount_roots", []))
    line(leader("USB BUS", cols) + f"{len(drives)} DRIVE(S)")
    line(leader("NETWORK", cols) + (system.local_ip() or "OFFLINE"))

    if cfg.get("update", {}).get("check_on_boot", True) and system.local_ip():
        scr.put(row, 1, leader("UPDATES", cols) + "...")
        scr.refresh()
        status = updater.check(cfg, fetch_timeout=8)
        ctx["update"] = status
        line(leader("UPDATES", cols) + short_status(status).ljust(12))

    for key in ("_error", "_notice"):
        if cfg.get(key):
            line(f"! {cfg[key]}", scr.bright)
    row += 1
    line("READY.", scr.bright, wait=0.5)
    scr.skip_effects = False


def main_menu(scr, cfg: dict, ctx: dict) -> None:
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


def start(scr, cfg: dict, no_boot: bool = False) -> None:
    ctx: dict = {"update": None}
    try:
        if not no_boot:
            boot(scr, cfg, ctx)
        main_menu(scr, cfg, ctx)
    except system.ExitToShell:
        return
