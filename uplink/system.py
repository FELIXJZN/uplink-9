"""Talking to the real machine: commands, USB drives, network, VPN, power and system info."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

IS_LINUX = platform.system() == "Linux"


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(args, timeout=30, sudo_fallback=False):
    """Run a command. Returns (ok, output). Tries 'sudo -n' once if allowed and permission was denied."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + p.stderr).strip()
        if p.returncode != 0 and sudo_fallback and have("sudo") and re.search(r"permission|denied|access|root|operator", out, re.I):
            p = subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout)
            out = (p.stdout + p.stderr).strip()
        return p.returncode == 0, out
    except FileNotFoundError:
        return False, f"{args[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{args[0]} timed out"


# ---------------------------------------------------------------- USB drives
@dataclass
class Drive:
    path: str          # /dev/sda1
    disk: str          # /dev/sda
    label: str
    size: int
    fstype: str
    mountpoint: str
    model: str

    @property
    def name(self) -> str:
        return (self.label or self.model or os.path.basename(self.path)).upper()


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def parse_lsblk(data: dict) -> list[Drive]:
    drives: list[Drive] = []

    def walk(dev, disk, removable, model):
        kids = dev.get("children") or []
        if dev.get("fstype") and dev.get("type") in ("part", "disk") and removable:
            mp = dev.get("mountpoint")
            if mp is None and dev.get("mountpoints"):
                mp = next((m for m in dev["mountpoints"] if m), None)
            drives.append(Drive(
                path=dev.get("path") or "/dev/" + dev["name"],
                disk=disk, label=dev.get("label") or "", size=int(dev.get("size") or 0),
                fstype=dev.get("fstype") or "", mountpoint=mp or "", model=(model or "").strip(),
            ))
        for k in kids:
            walk(k, disk, removable, model)

    for d in data.get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        removable = bool(d.get("rm")) or bool(d.get("hotplug")) or d.get("tran") == "usb"
        walk(d, d.get("path") or "/dev/" + d["name"], removable, d.get("model"))
    return drives


def list_drives() -> list[Drive]:
    if not (IS_LINUX and have("lsblk")):
        return []
    ok, out = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,LABEL,SIZE,RM,HOTPLUG,TRAN,MOUNTPOINT,FSTYPE,TYPE,MODEL"], timeout=5)
    if not ok:
        return []
    try:
        return parse_lsblk(json.loads(out))
    except ValueError:
        return []


def mount(drive: Drive):
    if not have("udisksctl"):
        return False, "udisksctl missing: sudo apt install udisks2"
    ok, out = run(["udisksctl", "mount", "-b", drive.path, "--no-user-interaction"])
    m = re.search(r" at (.+?)\.?$", out)
    if ok and m:
        drive.mountpoint = m.group(1).strip()
    return ok, out


def unmount(drive: Drive):
    os.sync()
    return run(["udisksctl", "unmount", "-b", drive.path, "--no-user-interaction"])


def eject(drive: Drive):
    os.sync()
    if drive.mountpoint:
        ok, out = unmount(drive)
        if not ok:
            return ok, out
    return run(["udisksctl", "power-off", "-b", drive.disk, "--no-user-interaction"])


# ---------------------------------------------------------------- network
def ping(host: str):
    """Returns latency in ms, or None if unreachable."""
    if not have("ping"):
        return None
    args = ["ping", "-n", "1", "-w", "1000", host] if platform.system() == "Windows" else ["ping", "-c", "1", "-W", "1", host]
    ok, out = run(args, timeout=4)
    if not ok:
        return None
    m = re.search(r"time[=<]\s*([\d.]+)", out)
    return float(m.group(1)) if m else 0.0


def wake_on_lan(mac: str) -> tuple[bool, str]:
    hexes = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexes) != 12:
        return False, "MAC ADDRESS MUST HAVE 12 HEX DIGITS"
    packet = bytes.fromhex("FF" * 6 + hexes * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, ("255.255.255.255", 9))
    return True, "MAGIC PACKET SENT"


def tailscale_status():
    """Returns (state, ip, peers) where peers is a list of (hostname, online)."""
    if not have("tailscale"):
        return "NOT INSTALLED", "", []
    ok, out = run(["tailscale", "status", "--json"], timeout=5)
    try:
        data = json.loads(out)
    except ValueError:
        return "STOPPED", "", []
    state = (data.get("BackendState") or "UNKNOWN").upper()
    ips = (data.get("Self") or {}).get("TailscaleIPs") or []
    peers = [((p.get("HostName") or "?"), bool(p.get("Online"))) for p in (data.get("Peer") or {}).values()]
    return state, (ips[0] if ips else ""), sorted(peers)


def twingate_status():
    if not have("twingate"):
        return "NOT INSTALLED"
    ok, out = run(["twingate", "status"], timeout=8)
    return out.strip().splitlines()[0].upper() if out.strip() else "UNKNOWN"


def vpn_set(target: str):
    """target: TAILSCALE, TWINGATE or OFF. Only one tunnel at a time."""
    msgs = []
    if target != "TAILSCALE" and have("tailscale"):
        msgs.append(run(["tailscale", "down"], sudo_fallback=True)[1])
    if target != "TWINGATE" and have("twingate"):
        msgs.append(run(["twingate", "stop"], sudo_fallback=True)[1])
    if target == "TAILSCALE":
        ok, out = run(["tailscale", "up"], timeout=40, sudo_fallback=True)
        return ok, out
    if target == "TWINGATE":
        ok, out = run(["twingate", "start"], timeout=40, sudo_fallback=True)
        return ok, out
    return True, "\n".join(m for m in msgs if m) or "TUNNELS STOPPED"


# ---------------------------------------------------------------- system
def sysinfo() -> list[tuple[str, str]]:
    info = [("HOST", socket.gethostname().upper())]
    model = ""
    for p in ("/proc/device-tree/model", "/sys/devices/virtual/dmi/id/product_name"):
        try:
            model = Path(p).read_text(errors="ignore").strip("\x00\n ")
            if model:
                break
        except OSError:
            pass
    info.append(("MODEL", (model or platform.machine()).upper()))
    info.append(("KERNEL", platform.release().upper()))
    try:
        mem = Path("/proc/meminfo").read_text()
        kb = int(re.search(r"MemTotal:\s+(\d+)", mem).group(1))
        info.append(("MEMORY", f"{kb // 1024} MB"))
    except (OSError, AttributeError):
        pass
    try:
        du = shutil.disk_usage(Path.home())
        info.append(("STORAGE", f"{human(du.used)} / {human(du.total)}"))
    except OSError:
        pass
    if have("hostname") and IS_LINUX:
        ok, out = run(["hostname", "-I"], timeout=3)
        if ok and out:
            info.append(("IP", out.split()[0]))
    return info


def power(action: str):
    """action: poweroff or reboot."""
    return run(["systemctl", action], timeout=10)
