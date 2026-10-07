"""Tests for the parts that talk to the system: USB parsing, config repair, updater."""
import json
import os
import subprocess

from uplink import storage
from uplink.system import parse_lsblk

LSBLK = {"blockdevices": [
    {"name": "mmcblk0", "path": "/dev/mmcblk0", "size": 63864569856, "rm": False, "hotplug": False, "tran": None,
     "fstype": None, "type": "disk", "model": None, "children": [
         {"name": "mmcblk0p2", "path": "/dev/mmcblk0p2", "label": "rootfs", "size": 63327698944, "rm": False,
          "hotplug": False, "mountpoint": "/", "fstype": "ext4", "type": "part"}]},
    {"name": "sda", "path": "/dev/sda", "size": 32010928128, "rm": True, "hotplug": True, "tran": "usb",
     "fstype": None, "type": "disk", "model": "SanDisk 3.2Gen1  ", "children": [
         {"name": "sda1", "path": "/dev/sda1", "label": "STEMS", "size": 32009879552, "rm": True,
          "mountpoint": "/media/felix/STEMS", "fstype": "exfat", "type": "part"}]},
    {"name": "sdb", "path": "/dev/sdb", "label": "RAWSTICK", "size": 8004304896, "rm": True, "tran": "usb",
     "mountpoint": None, "fstype": "vfat", "type": "disk", "model": "Generic"},
    {"name": "sdc", "path": "/dev/sdc", "size": 16000000000, "rm": True, "tran": "usb", "type": "disk",
     "model": "Blank", "fstype": None, "mountpoints": [None]},
]}


def test_usb_parsing_skips_internal_card():
    drives = parse_lsblk(LSBLK)
    assert [(d.name, d.path, d.disk, d.mountpoint) for d in drives] == [
        ("STEMS", "/dev/sda1", "/dev/sda", "/media/felix/STEMS"),
        ("RAWSTICK", "/dev/sdb", "/dev/sdb", ""),
    ]


def test_broken_config_is_kept_aside(home):
    storage.Config.path.parent.mkdir(parents=True, exist_ok=True)
    storage.Config.path.write_text('{"nodes": [ {"name": "PVE-1", "host": "pve-1",} ]')   # typo
    cfg = storage.Config()
    assert cfg["nodes"][0]["name"] == "PVE-1"                       # defaults
    assert (storage.Config.path.parent / "config.json.broken").exists()
    assert any("ERROR" in p for p in storage.LOAD_PROBLEMS)


def test_bad_entries_are_repaired(home):
    storage.Config.path.parent.mkdir(parents=True, exist_ok=True)
    storage.Config.path.write_text(json.dumps({
        "nodes": [{"name": "pve-1"}, {"host": "10.0.0.5"}, "junk"],
        "webhooks": [{"name": "x", "url": "ftp://nope"}, {"url": "https://ntfy.sh/topic", "format": "WEIRD"}],
        "color": 5,
    }))
    cfg = storage.Config()
    assert cfg["nodes"] == [{"name": "10.0.0.5", "host": "10.0.0.5", "role": "", "mac": ""}]
    assert len(cfg["webhooks"]) == 1 and cfg["webhooks"][0]["format"] == "JSON"
    assert cfg["color"] == "GREEN"


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def test_updater_install_and_rollback(tmp_path, monkeypatch):
    from uplink import updater
    origin, dev, device = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "device"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    dev.mkdir()
    (dev / "VERSION").write_text("1.0.0\n")
    (dev / "requirements.txt").write_text("")
    git("init", "-q", "-b", "main", cwd=dev)
    git("add", "-A", cwd=dev)
    git("commit", "-qm", "first", cwd=dev)
    git("remote", "add", "origin", str(origin), cwd=dev)
    git("push", "-q", "origin", "main", cwd=dev)
    git("clone", "-q", str(origin), str(device), cwd=tmp_path)
    (dev / "VERSION").write_text("1.0.1\n")
    git("commit", "-qam", "Fix a thing", cwd=dev)
    git("push", "-q", "origin", "main", cwd=dev)

    monkeypatch.setattr(updater, "APP_DIR", device)
    info = updater.check("main")
    assert info["ok"] and info["behind"] == 1 and info["version"] == "1.0.1"
    assert info["changes"] == ["Fix a thing"]
    ok, msg, prev = updater.install("main")
    assert ok and updater.local_version() == "1.0.1"
    assert updater.check("main")["behind"] == 0
    ok, _ = updater.rollback(prev)
    assert ok and updater.local_version() == "1.0.0"


def test_updater_refuses_local_changes(tmp_path, monkeypatch):
    from uplink import updater
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "VERSION").write_text("1.0.0\n")
    git("init", "-q", "-b", "main", cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "x", cwd=repo)
    (repo / "VERSION").write_text("hacked\n")
    monkeypatch.setattr(updater, "APP_DIR", repo)
    ok, msg, _ = updater.install("main")
    assert not ok and "LOCAL CHANGES" in msg
