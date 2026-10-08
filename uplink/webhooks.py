"""Outgoing webhooks: Discord, ntfy, or any URL that takes JSON."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import __version__
from . import config as config_mod

FORMATS = ["json", "discord", "ntfy"]


def build_payload(hook: dict, event: str, text: str, source: str = "UPLINK-9",
                  extra: dict | None = None) -> tuple[bytes, dict]:
    """Return (body, headers) for a webhook in the hook's format."""
    fmt = hook.get("format", "json")
    if fmt == "discord":
        body = {"username": source, "content": f"**[{event}]** {text}"[:2000]}
        return json.dumps(body).encode(), {"Content-Type": "application/json"}
    if fmt == "ntfy":
        return text.encode(), {"Content-Type": "text/plain; charset=utf-8",
                               "Title": f"{source}: {event}"}
    body = {
        "source": source,
        "event": event,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        body.update(extra)
    return json.dumps(body).encode(), {"Content-Type": "application/json"}


def send(hook: dict, event: str, text: str, source: str = "UPLINK-9",
         extra: dict | None = None, timeout: float = 10) -> tuple[bool, str]:
    """Fire one webhook. Returns (ok, short status text). Never raises."""
    url = hook.get("url", "")
    if not url.startswith(("http://", "https://")):
        return False, "URL must start with http:// or https://"
    body, headers = build_payload(hook, event, text, source, extra)
    headers["User-Agent"] = f"uplink-9/{__version__}"
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=hook.get("method", "POST"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"NO CONNECTION ({reason})"


def find(cfg: dict, name: str) -> dict | None:
    for hook in cfg.get("webhooks", []):
        if hook.get("name") == name:
            return hook
    return None


# ---- screen ---------------------------------------------------------------

def _fire(scr, cfg, hook, event, text):
    scr.busy("WEBHOOKS", f"TRANSMITTING TO {hook['name'].upper()} ...")
    ok, status = send(hook, event, text, cfg.get("callsign", "UPLINK-9"))
    scr.pager("WEBHOOKS", [("SENT" if ok else "FAILED") + f": {status}"])


def _add(scr, cfg):
    name = scr.prompt("ADD WEBHOOK", "NAME (e.g. discord):")
    if not name:
        return
    url = scr.prompt("ADD WEBHOOK", "URL:")
    if not url:
        return
    fmt = scr.menu("FORMAT", ["json  (generic)", "discord", "ntfy"])
    if fmt is None:
        return
    cfg.setdefault("webhooks", []).append({"name": name, "url": url, "format": FORMATS[fmt]})
    config_mod.save(cfg)


def run(scr, cfg, ctx):
    sel = 0
    while True:
        hooks = cfg.get("webhooks", [])
        items = [f"{h['name'].upper()}  [{h.get('format', 'json')}]" for h in hooks]
        items.append("+ ADD WEBHOOK")
        sel = scr.menu("WEBHOOKS", items, start=sel)
        if sel is None:
            return
        if sel == len(hooks):
            _add(scr, cfg)
            continue
        hook = hooks[sel]
        choice = scr.menu(hook["name"].upper(), ["SEND TEST PING", "SEND MESSAGE", "REMOVE"])
        if choice == 0:
            _fire(scr, cfg, hook, "ping", "Test ping from the terminal.")
        elif choice == 1:
            text = scr.prompt(hook["name"].upper(), "MESSAGE:")
            if text:
                _fire(scr, cfg, hook, "message", text)
        elif choice == 2 and scr.confirm("WEBHOOKS", f"Remove {hook['name']}?"):
            hooks.pop(sel)
            sel = 0
            config_mod.save(cfg)
