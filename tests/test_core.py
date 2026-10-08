"""Unit tests. Run with:  python3 -m unittest discover tests"""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from uplink import config, holotapes, messages, updater, usb, webhooks


class TempDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["UPLINK_CONFIG_DIR"] = str(self.root / "cfg")
        os.environ["UPLINK_DATA_DIR"] = str(self.root / "data")

    def tearDown(self):
        self.tmp.cleanup()


class ConfigTests(TempDirs):
    def test_defaults_when_missing(self):
        self.assertEqual(config.load(), config.DEFAULTS)

    def test_merge_keeps_nested_defaults(self):
        path = config.config_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"effects": {"typing": False}}))
        cfg = config.load()
        self.assertFalse(cfg["effects"]["typing"])
        self.assertTrue(cfg["effects"]["flicker"])

    def test_broken_file_falls_back(self):
        path = config.config_path()
        path.parent.mkdir(parents=True)
        path.write_text("{nope")
        self.assertIn("_error", config.load())

    def test_save_skips_runtime_keys(self):
        cfg = config.load()
        cfg["_cli_plain"] = True
        cfg["callsign"] = "TEST"
        config.save(cfg)
        saved = json.loads(config.config_path().read_text())
        self.assertEqual(saved["callsign"], "TEST")
        self.assertNotIn("_cli_plain", saved)

    def test_example_matches_defaults(self):
        example = Path(__file__).resolve().parent.parent / "config.example.json"
        self.assertEqual(json.loads(example.read_text()), config.DEFAULTS)


class HolotapeTests(TempDirs):
    def test_save_list_delete(self):
        d = holotapes.tape_dir()
        a = holotapes.save_tape(d, "first", "hello", tape_id="20260101-000000-aaaaaa")
        holotapes.save_tape(d, "second", "world", tape_id="20260102-000000-bbbbbb")
        self.assertEqual(len(holotapes.list_tapes(d)), 2)
        holotapes.delete_tape(d, a)
        self.assertEqual([t["title"] for t in holotapes.list_tapes(d)], ["second"])

    def test_export_import_roundtrip(self):
        d = holotapes.tape_dir()
        holotapes.save_tape(d, "log", "text")
        (d / "x.wav").write_bytes(b"RIFF")
        holotapes.save_tape(d, "audio", "", audio="x.wav")
        drive = self.root / "drive"
        self.assertEqual(holotapes.export_tapes(d, drive), 2)
        other = self.root / "other"
        other.mkdir()
        self.assertEqual(holotapes.import_tapes(drive, other), 2)
        self.assertTrue((other / "x.wav").exists())
        self.assertEqual(holotapes.import_tapes(drive, other), 0)  # no duplicates


class UsbTests(unittest.TestCase):
    MOUNTS = (
        "/dev/mmcblk0p2 / ext4 rw 0 0\n"
        "proc /proc proc rw 0 0\n"
        "/dev/sda1 /media/felix/MY\\040STICK vfat rw 0 0\n"
        "/dev/sdb1 /run/media/felix/DATA exfat rw 0 0\n"
        "tmpfs /media/felix/tmp tmpfs rw 0 0\n"
    )

    def test_mounted_drives(self):
        drives = usb.mounted_drives(["/media", "/run/media"], self.MOUNTS)
        self.assertEqual([d.mountpoint for d in drives],
                         ["/media/felix/MY STICK", "/run/media/felix/DATA"])
        self.assertEqual(drives[0].name, "MY STICK")

    def test_unmounted_partitions(self):
        data = {"blockdevices": [
            {"name": "mmcblk0", "rm": False, "hotplug": False, "type": "disk", "children": [
                {"name": "mmcblk0p2", "type": "part", "fstype": "ext4", "mountpoint": "/"}]},
            {"name": "sda", "rm": True, "type": "disk", "fstype": None, "children": [
                {"name": "sda1", "path": "/dev/sda1", "type": "part", "fstype": "vfat",
                 "label": "STICK", "size": "7.5G", "mountpoint": None},
                {"name": "sda2", "type": "part", "fstype": "ext4", "mountpoints": ["/media/x"]}]},
        ]}
        found = usb.unmounted_partitions(json.dumps(data))
        self.assertEqual(found, [{"path": "/dev/sda1", "label": "STICK", "size": "7.5G"}])

    def test_text_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, binary = Path(tmp, "a.txt"), Path(tmp, "b.bin")
            text.write_text("line1\nline2")
            binary.write_bytes(b"\x00\x01")
            self.assertEqual(usb.read_text_file(text), ["line1", "line2"])
            self.assertIsNone(usb.read_text_file(binary))

    def test_human_size(self):
        self.assertEqual(usb.human_size(512), "512B")
        self.assertEqual(usb.human_size(1536), "1.5K")


class _Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Handler.received.append((self.headers["Content-Type"], body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class WebhookTests(TempDirs):
    def test_payload_formats(self):
        body, headers = webhooks.build_payload({"format": "discord"}, "ping", "hi")
        self.assertEqual(json.loads(body)["content"], "**[ping]** hi")
        body, headers = webhooks.build_payload({"format": "ntfy"}, "ping", "hi")
        self.assertEqual(body, b"hi")
        body, _ = webhooks.build_payload({}, "ping", "hi", extra={"to": "bob"})
        data = json.loads(body)
        self.assertEqual((data["event"], data["to"]), ("ping", "bob"))

    def test_send_to_local_server(self):
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.handle_request, daemon=True).start()
        hook = {"name": "t", "url": f"http://127.0.0.1:{server.server_port}/", "format": "json"}
        ok, status = webhooks.send(hook, "ping", "hello")
        server.server_close()
        self.assertTrue(ok, status)
        self.assertEqual(json.loads(_Handler.received[-1][1])["text"], "hello")

    def test_bad_url_and_offline(self):
        self.assertFalse(webhooks.send({"url": "ftp://x"}, "e", "t")[0])
        ok, status = webhooks.send({"url": "http://127.0.0.1:9/"}, "e", "t", timeout=2)
        self.assertFalse(ok)
        self.assertIn("NO CONNECTION", status)

    def test_messages_log(self):
        path = messages.log_path()
        messages.append(path, messages.make_message("bob", "hey", "UPLINK-9"))
        self.assertEqual(messages.load_all(path)[0]["to"], "bob")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class UpdaterTests(unittest.TestCase):
    """Builds a fake GitHub (bare repo) plus a device clone and updates between them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dev, self.remote, self.device = root / "dev", root / "remote.git", root / "device"
        _git(root, "init", "-q", "--bare", str(self.remote))
        _git(root, "init", "-q", "-b", "main", str(self.dev))
        for key, val in (("user.name", "t"), ("user.email", "t@t")):
            _git(self.dev, "config", key, val)
        self.commit("v1")
        _git(self.dev, "tag", "v0.1.0")
        _git(self.dev, "remote", "add", "origin", str(self.remote))
        _git(self.dev, "push", "-q", "origin", "main", "--tags")
        _git(root, "clone", "-q", str(self.remote), str(self.device))
        _git(self.device, "checkout", "-q", "--detach", "v0.1.0")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, text):
        (self.dev / "f.txt").write_text(text)
        _git(self.dev, "add", ".")
        _git(self.dev, "commit", "-q", "-m", text)

    def cfg(self, channel):
        return {"update": {"remote": "origin", "channel": channel, "branch": "main"}}

    def test_tags_channel(self):
        self.assertEqual(updater.check(self.cfg("tags"), self.device).message, "UP TO DATE")
        self.commit("v2")  # untagged commit: not offered on the tags channel
        _git(self.dev, "push", "-q", "origin", "main")
        self.assertFalse(updater.check(self.cfg("tags"), self.device).available)
        _git(self.dev, "tag", "v0.2.0")
        _git(self.dev, "push", "-q", "origin", "--tags")
        status = updater.check(self.cfg("tags"), self.device)
        self.assertTrue(status.available)
        self.assertEqual(status.target, "v0.2.0")
        ok, msg = updater.apply(self.cfg("tags"), self.device)
        self.assertTrue(ok, msg)
        self.assertEqual((self.device / "f.txt").read_text(), "v2")

    def test_branch_channel_and_dirty_guard(self):
        _git(self.device, "checkout", "-q", "main")
        self.commit("v2")
        _git(self.dev, "push", "-q", "origin", "main")
        (self.device / "f.txt").write_text("edited on device")
        ok, msg = updater.apply(self.cfg("branch"), self.device)
        self.assertFalse(ok)
        self.assertIn("EDITED", msg)
        _git(self.device, "checkout", "--", "f.txt")
        ok, msg = updater.apply(self.cfg("branch"), self.device)
        self.assertTrue(ok, msg)
        self.assertEqual((self.device / "f.txt").read_text(), "v2")

    def test_never_downgrades(self):
        _git(self.device, "checkout", "-q", "main")
        self.commit("v2")  # device runs newer code than the newest tag
        _git(self.dev, "push", "-q", "origin", "main")
        _git(self.device, "pull", "-q")
        self.assertEqual(updater.check(self.cfg("tags"), self.device).message, "UP TO DATE")


if __name__ == "__main__":
    unittest.main()
