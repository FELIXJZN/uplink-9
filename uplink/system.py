"""System screen: updates, plain mode, device info, power."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from . import __version__
from . import config as config_mod
from . import updater


class Restart(Exception):
    """Raised to restart the app (after an update or a settings change)."""


class ExitToShell(Exception):
    """Raised to leave UPLINK and drop to the normal Linux shell."""


def local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 53))  # no packet is sent for UDP connect
            return sock.getsockname()[0]
    except OSError:
        return None


def battery() -> str | None:
    for supply in Path("/sys/class/power_supply").glob("*"):
        cap = supply / "capacity"
        if cap.exists():
            try:
                level = cap.read_text().strip()
                state = (supply / "status").read_text().strip() if (supply / "status").exists() else ""
            except OSError:
                continue
            return f"{level}% {state}".strip()
    return None


def uptime() -> str | None:
    try:
        secs = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None
    return f"{secs // 86400}d {secs % 86400 // 3600}h {secs % 3600 // 60}m"


def mem_total_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def info_lines() -> list[str]:
    disk = shutil.disk_usage(str(config_mod.data_dir()))
    return [
        f"{'VERSION':.<12} {__version__} ({updater.current_version()})",
        f"{'HOST':.<12} {socket.gethostname()}",
        f"{'NETWORK':.<12} {local_ip() or 'OFFLINE'}",
        f"{'BATTERY':.<12} {battery() or 'N/A'}",
        f"{'UPTIME':.<12} {uptime() or '?'}",
        f"{'MEMORY':.<12} {mem_total_mb() or '?'} MB",
        f"{'DISK FREE':.<12} {disk.free // (1024 ** 2)} MB",
        f"{'DATA':.<12} {config_mod.data_dir()}",
        f"{'CONFIG':.<12} {config_mod.config_path()}",
    ]


def _power(scr, verb: str) -> None:
    if not scr.confirm(verb.upper(), f"{verb.capitalize()} the device now?"):
        return
    os.sync()
    try:
        res = subprocess.run(["systemctl", verb], capture_output=True, text=True, timeout=15)
        err = res.stderr.strip() if res.returncode else ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        err = str(exc)
    if err:
        scr.pager(verb.upper(), [f"{verb} failed:", err])


def run(scr, cfg, ctx):
    sel = 0
    while True:
        status = ctx.get("update")
        badge = " (!)" if status and status.available else ""
        plain = "ON" if cfg.get("plain_mode") else "OFF"
        items = ["CHECK FOR UPDATES", f"INSTALL UPDATE{badge}", f"PLAIN MODE: {plain}",
                 "SYSTEM INFO", "EXIT TO SHELL", "REBOOT", "SHUT DOWN"]
        sel = scr.menu("SYSTEM", items, start=sel)
        if sel is None:
            return
        if sel == 0:
            scr.busy("UPDATES", "CONTACTING GITHUB ...")
            ctx["update"] = updater.check(cfg)
            s = ctx["update"]
            scr.pager("UPDATES", [f"RUNNING: {s.current}", s.message])
        elif sel == 1:
            scr.busy("UPDATES", "DOWNLOADING AND INSTALLING ...")
            ok, msg = updater.apply(cfg)
            scr.pager("UPDATES", [msg] + (["", "RESTARTING TERMINAL."] if ok else []))
            if ok:
                raise Restart()
        elif sel == 2:
            cfg["plain_mode"] = not cfg.get("plain_mode")
            config_mod.save(cfg)
            raise Restart()
        elif sel == 3:
            scr.pager("SYSTEM INFO", info_lines())
        elif sel == 4:
            if scr.confirm("EXIT", "Leave the terminal and drop to the Linux shell?"):
                raise ExitToShell()
        elif sel == 5:
            _power(scr, "reboot")
        elif sel == 6:
            _power(scr, "poweroff")
