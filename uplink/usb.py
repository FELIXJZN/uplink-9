"""USB drives: find, mount, browse, read/write, eject.

Mounting/ejecting uses udisksctl (package: udisks2) so no root is needed.
Already-mounted drives under /media, /run/media or /mnt are picked up too.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config as config_mod
from . import holotapes

MAX_VIEW_BYTES = 256 * 1024


@dataclass
class Drive:
    device: str
    mountpoint: str
    fstype: str

    @property
    def name(self) -> str:
        return Path(self.mountpoint).name or self.device


def _unescape(path: str) -> str:
    """/proc/mounts writes spaces etc. as octal escapes like \\040."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def mounted_drives(roots, mounts_text: str | None = None) -> list[Drive]:
    if mounts_text is None:
        try:
            mounts_text = Path("/proc/mounts").read_text()
        except OSError:
            return []
    roots = [r.rstrip("/") for r in roots]
    drives = []
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[0].startswith("/dev/"):
            continue
        mnt = _unescape(parts[1])
        if any(mnt.startswith(root + "/") for root in roots):
            drives.append(Drive(parts[0], mnt, parts[2]))
    return drives


def _flag(value) -> bool:
    return value in (True, 1, "1", "true")


def unmounted_partitions(lsblk_json: str) -> list[dict]:
    """Removable/hotplug partitions with a filesystem that aren't mounted yet."""
    try:
        devices = json.loads(lsblk_json).get("blockdevices", [])
    except ValueError:
        return []
    found = []

    def walk(dev, parent_removable=False):
        removable = parent_removable or _flag(dev.get("rm")) or _flag(dev.get("hotplug"))
        mounts = dev.get("mountpoints") or [dev.get("mountpoint")]
        mounted = any(m for m in mounts if m)
        if removable and dev.get("fstype") and not mounted and dev.get("type") in ("part", "disk"):
            found.append({
                "path": dev.get("path") or f"/dev/{dev.get('name')}",
                "label": dev.get("label") or dev.get("name"),
                "size": dev.get("size") or "?",
            })
        for child in dev.get("children") or []:
            walk(child, removable)

    for dev in devices:
        walk(dev)
    return found


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    out = (res.stdout + res.stderr).strip()
    return res.returncode == 0, out


def scan_unmounted() -> list[dict]:
    if not shutil.which("lsblk"):
        return []
    cols = "NAME,PATH,RM,HOTPLUG,TYPE,FSTYPE,LABEL,SIZE,MOUNTPOINT"
    ok, out = _run(["lsblk", "-J", "-o", cols])
    if not ok:  # older util-linux has no PATH column
        ok, out = _run(["lsblk", "-J", "-o", cols.replace("PATH,", "")])
    return unmounted_partitions(out) if ok else []


def mount(path: str) -> tuple[bool, str]:
    if not shutil.which("udisksctl"):
        return False, "udisksctl not found - install udisks2"
    return _run(["udisksctl", "mount", "-b", path])


def eject(drive: Drive) -> tuple[bool, str]:
    os.sync()
    if shutil.which("udisksctl"):
        return _run(["udisksctl", "unmount", "-b", drive.device])
    return _run(["umount", drive.mountpoint])


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}T"


def list_dir(path: Path) -> list[Path]:
    try:
        entries = [p for p in path.iterdir() if not p.name.startswith(".")]
    except OSError:
        return []
    return sorted(entries, key=lambda p: (not p.is_dir(), p.name.lower()))


def read_text_file(path: Path) -> list[str] | None:
    """Return the file's lines if it looks like text, else None."""
    try:
        data = path.read_bytes()[:MAX_VIEW_BYTES]
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace").splitlines()


def local_files_dir() -> Path:
    path = config_mod.data_dir() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---- screen ---------------------------------------------------------------

def _file_menu(scr, path: Path) -> bool:
    """Actions for one file. Returns True if the file was deleted."""
    try:
        size = human_size(path.stat().st_size)
    except OSError:
        size = "?"
    choice = scr.menu(f"{path.name.upper()} ({size})", ["VIEW", "COPY TO TERMINAL", "DELETE"])
    if choice == 0:
        lines = read_text_file(path)
        scr.pager(path.name.upper(), lines if lines is not None else ["(binary file - can't display)"])
    elif choice == 1:
        try:
            shutil.copy2(path, local_files_dir() / path.name)
            scr.pager("COPY", [f"Copied to {local_files_dir() / path.name}"])
        except OSError as exc:
            scr.pager("COPY", [f"Copy failed: {exc}"])
    elif choice == 2 and scr.confirm("DELETE", f"Delete {path.name} from the drive?"):
        try:
            path.unlink()
            return True
        except OSError as exc:
            scr.pager("DELETE", [f"Delete failed: {exc}"])
    return False


def _copy_to_drive(scr, folder: Path) -> None:
    files = [p for p in list_dir(local_files_dir()) if p.is_file()]
    if not files:
        scr.pager("COPY HERE", ["No files on the terminal yet.",
                                f"Files you copy off drives land in {local_files_dir()}"])
        return
    pick = scr.menu("COPY FILE HERE", [p.name for p in files])
    if pick is None:
        return
    try:
        shutil.copy2(files[pick], folder / files[pick].name)
        os.sync()
        scr.pager("COPY HERE", [f"Wrote {files[pick].name} to the drive."])
    except OSError as exc:
        scr.pager("COPY HERE", [f"Write failed: {exc}"])


def _browse(scr, root: Path) -> None:
    folder = root
    sel = 0
    while True:
        entries = list_dir(folder)
        items = ["+ COPY A FILE HERE"] + [p.name + ("/" if p.is_dir() else "") for p in entries]
        rel = "/" + str(folder.relative_to(root)) if folder != root else "/"
        sel = scr.menu(f"BROWSE {rel}", items, start=sel)
        if sel is None:
            if folder == root:
                return
            folder, sel = folder.parent, 0
            continue
        if sel == 0:
            _copy_to_drive(scr, folder)
            continue
        target = entries[sel - 1]
        if target.is_dir():
            folder, sel = target, 0
        elif _file_menu(scr, target):
            sel = 0


def _drive_menu(scr, drive: Drive) -> None:
    while True:
        choice = scr.menu(f"DRIVE {drive.name.upper()}",
                          ["BROWSE FILES", "EXPORT HOLOTAPES TO DRIVE",
                           "IMPORT HOLOTAPES FROM DRIVE", "EJECT"])
        if choice is None:
            return
        root = Path(drive.mountpoint)
        if choice == 0:
            _browse(scr, root)
        elif choice == 1:
            try:
                n = holotapes.export_tapes(holotapes.tape_dir(), root)
                os.sync()
                scr.pager("EXPORT", [f"{n} holotape(s) written to {holotapes.EXPORT_DIR}"])
            except OSError as exc:
                scr.pager("EXPORT", [f"Export failed: {exc}"])
        elif choice == 2:
            try:
                n = holotapes.import_tapes(root, holotapes.tape_dir())
                scr.pager("IMPORT", [f"{n} new holotape(s) imported."])
            except OSError as exc:
                scr.pager("IMPORT", [f"Import failed: {exc}"])
        elif choice == 3:
            scr.busy("EJECT", "SYNCING AND UNMOUNTING ...")
            ok, out = eject(drive)
            scr.pager("EJECT", ["SAFE TO REMOVE." if ok else "EJECT FAILED.", out])
            if ok:
                return


def run(scr, cfg, ctx):
    roots = cfg.get("usb", {}).get("mount_roots", ["/media", "/run/media", "/mnt"])
    while True:
        drives = mounted_drives(roots)
        waiting = scan_unmounted()
        items = [f"{d.name.upper()}  ({d.device})" for d in drives]
        items += [f"MOUNT {p['label'].upper()}  ({p['size']})" for p in waiting]
        items.append("RESCAN")
        sel = scr.menu("USB DRIVES", items)
        if sel is None:
            return
        if sel < len(drives):
            _drive_menu(scr, drives[sel])
        elif sel < len(drives) + len(waiting):
            part = waiting[sel - len(drives)]
            scr.busy("USB DRIVES", f"MOUNTING {part['label'].upper()} ...")
            ok, out = mount(part["path"])
            if not ok:
                scr.pager("MOUNT FAILED", [out])
