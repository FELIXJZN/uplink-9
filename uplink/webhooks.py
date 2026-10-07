"""Outgoing webhooks. Each hook has a format: JSON (any service), DISCORD, or NTFY (plain text)."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import __version__

EVENTS = [
    "boot", "usb.inserted", "usb.removed", "file.copied", "file.deleted",
    "tape.recorded", "message.sent", "node.down", "node.up", "vpn.changed", "update.installed",
]
FORMATS = ["JSON", "DISCORD", "NTFY"]


def new_hook(name: str, url: str) -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name, "url": url, "format": guess_format(url),
            "events": list(EVENTS), "enabled": True, "last": ""}


def guess_format(url: str) -> str:
    u = url.lower()
    if "discord.com/api/webhooks" in u or "discordapp.com/api/webhooks" in u:
        return "DISCORD"
    if "ntfy" in u:
        return "NTFY"
    return "JSON"


def build_request(hook: dict, event: str, summary: str, data: dict, device: str) -> urllib.request.Request:
    fmt = hook.get("format", "JSON")
    headers = {"User-Agent": f"uplink-9/{__version__}"}
    if fmt == "DISCORD":
        body = json.dumps({"content": f"**{device}** · {summary}"}).encode()
        headers["Content-Type"] = "application/json"
    elif fmt == "NTFY":
        body = summary.encode()
        headers["Title"] = f"{device}: {event}"
        headers["Tags"] = "computer"
    else:
        body = json.dumps({"event": event, "summary": summary, "device": device,
                           "host": socket.gethostname(), "version": __version__,
                           "time": int(time.time()), "data": data}).encode()
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(hook["url"], data=body, headers=headers, method="POST")


def send(hook: dict, event: str, summary: str, data: dict | None = None, device: str = "UPLINK-9") -> tuple[bool, str, str]:
    """Returns (ok, status, response body)."""
    body = ""
    try:
        req = build_request(hook, event, summary, data or {}, device)
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read(4096).decode(errors="ignore")
            ok, status = True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        ok, status = False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        ok, status = False, str(getattr(e, "reason", e)).upper()[:40]
    hook["last"] = ("OK " if ok else "FAIL ") + status + time.strftime(" %H:%M")
    return ok, status, body


def ntfy_poll(url: str, since: str) -> list[dict]:
    """Read new messages from an ntfy topic (two-way messaging). Returns [{id, time, message}]."""
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url.rstrip('/')}/json{sep}poll=1&since={since}",
                                 headers={"User-Agent": f"uplink-9/{__version__}"})
    out = []
    with urllib.request.urlopen(req, timeout=10) as r:
        for raw in r.read().decode(errors="ignore").splitlines():
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if m.get("event") == "message":
                out.append({"id": m.get("id", ""), "time": m.get("time", 0), "message": m.get("message", "")})
    return out


def fire(hooks: list[dict], event: str, summary: str, data: dict | None = None, device: str = "UPLINK-9",
         exclude: str = "", on_done=None) -> None:
    """Send an event to every enabled hook that listens for it, in the background."""
    targets = [h for h in hooks if h.get("enabled") and event in h.get("events", []) and h.get("id") != exclude]
    if not targets:
        return

    def worker():
        for h in targets:
            send(h, event, summary, data, device)
        if on_done:
            on_done()

    threading.Thread(target=worker, daemon=True).start()
