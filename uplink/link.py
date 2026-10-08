"""Phone link: a small HTTP API the Uplink-9 iPhone and Watch apps talk to.

Every request needs the token from the pairing QR code (Authorization: Bearer <token>).
Reads are answered from snapshots of the app's state; anything that changes state (sending a
message) runs on the terminal's UI thread so it can't race the screens.

Endpoints (all JSON):
    GET  /api/status              device vitals, drives, nodes, VPN, unread count
    GET  /api/messages            threads with their last 30 messages
    POST /api/messages/<thread>   {"text": "..."} sends a message in that thread
    GET  /api/tapes               holotapes (text lines)
"""
from __future__ import annotations

import hmac
import json
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import __version__, system, version_label

API_VERSION = 1
MAX_BODY = 4096


def new_token() -> str:
    return secrets.token_urlsafe(24)


def pair_url(host: str, port: int, token: str, name: str) -> str:
    """The link the pairing QR code holds; the iPhone's Camera app opens it in Uplink-9."""
    return f"uplink9://pair?host={quote(host)}&port={port}&token={quote(token)}&name={quote(name)}"


def condition(temp, bat) -> str:
    if temp is not None and temp >= 75:
        return "OVERHEATING"
    if bat and bat[0] < 15 and not bat[1]:
        return "LOW POWER"
    return "NOMINAL"


class LinkServer:
    def __init__(self, app):
        self.app = app
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self.httpd is not None

    def start(self, port: int, bind: str = "0.0.0.0") -> bool:
        self.stop()
        handler = self._handler()
        try:
            self.httpd = ThreadingHTTPServer((bind, port), handler)
        except OSError as e:
            self.httpd, self.error = None, (e.strerror or str(e)).upper()
            return False
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.error = ""
        return True

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1] if self.httpd else 0

    # ------------------------------------------------------------ data
    def status(self) -> dict:
        app = self.app
        bat, temp, mem = system.battery(), system.cpu_temp(), system.memory()
        try:
            du = shutil.disk_usage(Path.home())
            disk = (du.free, du.total)
        except OSError:
            disk = (0, 0)
        drives = []
        for d in list(app.drives):
            free = None
            if d.mountpoint:
                try:
                    free = shutil.disk_usage(d.mountpoint).free
                except OSError:
                    pass
            drives.append({"name": d.name, "size": d.size, "mounted": bool(d.mountpoint), "free": free})
        nodes = []
        for n in list(app.cfg["nodes"]):
            st = app.node_state.get(n["name"]) or {}
            nodes.append({"name": n["name"], "host": n["host"], "role": n.get("role", ""),
                          "up": st.get("up"), "ms": st.get("ms")})
        return {
            "api": API_VERSION,
            "device": app.cfg["device_name"],
            "version": version_label(__version__),
            "time": int(time.time()),
            "vitals": {
                "battery": bat[0] if bat else None, "charging": bool(bat and bat[1]),
                "temp": temp, "load": round(system.cpu_load(), 1),
                "mem_used": mem[0] if mem else None, "mem_total": mem[1] if mem else None,
                "disk_free": disk[0], "disk_total": disk[1], "uptime": int(system.uptime()),
            },
            "condition": condition(temp, bat),
            "drives": drives,
            "nodes": nodes,
            "vpn": (app.vpn_info or {}).get("active"),
            "unread": sum(t.get("unread", 0) for t in app.threads),
        }

    def messages(self) -> dict:
        out = []
        for t in list(self.app.threads):
            out.append({"id": t["id"], "name": t["name"], "unread": t.get("unread", 0),
                        "msgs": [{"me": bool(m.get("me")), "t": m["t"], "at": m.get("at", 0), "status": m.get("status", "")}
                                 for m in list(t["msgs"])[-30:]]})
        return {"threads": out}

    def tapes(self) -> dict:
        return {"tapes": [{"id": t["id"], "name": t["name"], "secs": t.get("secs", 0), "lines": t.get("lines", []),
                           "builtin": bool(t.get("builtin"))} for t in self.app.all_tapes()]}

    # ------------------------------------------------------------ http
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "Uplink9Link/1"

            def log_message(self, *args):   # keep the terminal screen clean
                pass

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                token = server.app.cfg.get("link_token", "")
                given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                ok = bool(token) and hmac.compare_digest(given.encode(), token.encode())
                if not ok:
                    time.sleep(0.5)          # slow down guessing
                    self._send(401, {"error": "WRONG OR MISSING TOKEN. PAIR AGAIN."})
                return ok

            def do_GET(self):
                if not self._authorized():
                    return
                try:
                    if self.path == "/api/status":
                        self._send(200, server.status())
                    elif self.path == "/api/messages":
                        self._send(200, server.messages())
                    elif self.path == "/api/tapes":
                        self._send(200, server.tapes())
                    else:
                        self._send(404, {"error": "NOT FOUND"})
                except Exception as e:   # a bad read must never take the terminal down
                    self._send(500, {"error": str(e)[:120]})

            def do_POST(self):
                if not self._authorized():
                    return
                parts = self.path.strip("/").split("/")
                if len(parts) != 3 or parts[:2] != ["api", "messages"]:
                    self._send(404, {"error": "NOT FOUND"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY:
                    self._send(400, {"error": "BODY MISSING OR TOO LARGE"})
                    return
                try:
                    text = str(json.loads(self.rfile.read(length)).get("text", "")).strip()[:500]
                except (ValueError, AttributeError):
                    self._send(400, {"error": "SEND JSON LIKE {\"text\": \"...\"}"})
                    return
                if not text:
                    self._send(400, {"error": "EMPTY MESSAGE"})
                    return
                try:
                    ok = server.app.call_from_thread(server.app.send_message_from_link, parts[2], text)
                except Exception as e:
                    self._send(500, {"error": str(e)[:120]})
                    return
                if ok:
                    self._send(200, {"ok": True})
                else:
                    self._send(404, {"error": "NO SUCH THREAD"})

        return Handler
