"""Messages: a local message log, optionally relayed out through a webhook.

Outgoing messages are always saved on the device. If config
messages.relay_webhook names one of your webhooks, each message is also sent
there (e.g. a Discord channel). Receiving messages needs a server to talk to,
which is on the roadmap.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from . import config as config_mod
from . import webhooks


def log_path() -> Path:
    return config_mod.data_dir() / "messages.jsonl"


def append(path: Path, msg: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(msg) + "\n")


def load_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    msgs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            msgs.append(json.loads(line))
        except ValueError:
            continue
    return msgs


def make_message(to: str, text: str, sender: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "ts": datetime.now().isoformat(timespec="seconds"),
        "from": sender,
        "to": to,
        "text": text,
        "delivered": None,
    }


# ---- screen ---------------------------------------------------------------

def _compose(scr, cfg):
    to = scr.prompt("NEW MESSAGE", "TO:")
    if not to:
        return
    text = scr.prompt("NEW MESSAGE", f"TO {to.upper()}:")
    if not text:
        return
    msg = make_message(to, text, cfg.get("callsign", "UPLINK-9"))
    relay = webhooks.find(cfg, cfg.get("messages", {}).get("relay_webhook", ""))
    status = "SAVED ON DEVICE."
    if relay:
        scr.busy("NEW MESSAGE", f"RELAYING VIA {relay['name'].upper()} ...")
        ok, info = webhooks.send(relay, "message", f"to {to}: {text}", msg["from"],
                                 extra={"to": to})
        msg["delivered"] = ok
        status += f" RELAY {'OK' if ok else 'FAILED'} ({info})"
    append(log_path(), msg)
    scr.pager("NEW MESSAGE", [status])


def _pick_relay(scr, cfg):
    names = [h["name"] for h in cfg.get("webhooks", [])]
    pick = scr.menu("RELAY", ["NONE (local only)"] + names)
    if pick is None:
        return
    cfg.setdefault("messages", {})["relay_webhook"] = "" if pick == 0 else names[pick - 1]
    config_mod.save(cfg)


def run(scr, cfg, ctx):
    while True:
        msgs = load_all(log_path())
        relay = cfg.get("messages", {}).get("relay_webhook") or "NONE"
        choice = scr.menu("MESSAGES", ["COMPOSE", f"LOG ({len(msgs)})", f"RELAY: {relay.upper()}"])
        if choice is None:
            return
        if choice == 0:
            _compose(scr, cfg)
        elif choice == 1:
            lines = []
            for m in reversed(msgs):
                mark = {True: " [SENT]", False: " [FAILED]"}.get(m.get("delivered"), "")
                lines += [f"{m.get('ts', '').replace('T', ' ')}  {m.get('from')} > {m.get('to')}{mark}",
                          m.get("text", ""), ""]
            scr.pager("MESSAGE LOG", lines or ["No messages yet."])
        elif choice == 2:
            _pick_relay(scr, cfg)
