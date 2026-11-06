#!/usr/bin/env python3
"""The TwoKey board: the two keys, the service and the ledger, live, on port 8787.

Reads what really happened and invents nothing. The change and ledger come from
TWOKEY_HOME, the service's state from a live request, and who approved each key
from Switch's own record of the approval (TWOKEY_APPROVALS_CMD, optional).
"""
import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
HOME = Path(os.environ.get("TWOKEY_HOME", ".twokey"))
SERVICE = os.environ.get("TWOKEY_SERVICE", "http://127.0.0.1:8099/quote?items=3")
APPROVALS_CMD = os.environ.get("TWOKEY_APPROVALS_CMD", "")
PLATFORMS = {"webex": "Webex", "rocketchat": "Rocket.Chat"}


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def ledger() -> list[dict]:
    try:
        lines = (HOME / "ledger.jsonl").read_text().splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line]


def service() -> dict:
    try:
        with urllib.request.urlopen(SERVICE, timeout=2) as reply:
            return {"status": reply.status, "body": json.load(reply)}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "body": None}
    except (OSError, ValueError):
        return {"status": 0, "body": None}


def who(actor: str) -> dict:
    """`@switch-webex-<bridge>-ada-lovelace:host` to a name and a platform."""
    found = re.match(r"@switch-([a-z]+)-[0-9a-f-]{36}-([^:]+)", actor or "")
    if found is None:
        return {"name": actor or "", "platform": ""}
    name = found.group(2).replace("-", " ").title()
    return {"name": name, "platform": PLATFORMS.get(found.group(1), found.group(1))}


def approvals() -> dict:
    """Who answered each key's approval, from Switch."""
    if not APPROVALS_CMD:
        return {}
    done = subprocess.run(shlex.split(APPROVALS_CMD), capture_output=True, text=True)
    answered: dict = {}
    for line in done.stdout.splitlines():
        detail, actor, state, room = (line.split("\t") + ["", "", "", ""])[:4]
        party = "vendor" if "twokey ship" in detail or "turn vendor" in detail else "customer"
        if party not in answered:
            answered[party] = {**who(actor), "state": state, "room": room}
    return answered


def state() -> dict:
    return {
        "change": read_json(HOME / "change.json"),
        "ledger": ledger(),
        "service": service(),
        "approvals": approvals(),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/state":
            body, kind = json.dumps(state()).encode(), "application/json"
        else:
            body, kind = (HERE / "index.html").read_bytes(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


if __name__ == "__main__":
    print("TwoKey board: http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
