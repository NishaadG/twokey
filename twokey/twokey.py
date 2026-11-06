#!/usr/bin/env python3
"""TwoKey: a change to a production system runs only when both companies have signed it.

  twokey init                     make a signing key for each party
  twokey propose PATCH -s TEXT    open a change for that exact patch
  twokey ship -s TEXT < PATCH     open a change and turn the vendor's key on it
  twokey turn vendor|customer     sign the open change; the second key applies it
  twokey status                   show the open change and its keys
  twokey audit                    check the ledger

Keys are Ed25519, signed and checked by OpenSSH, so there is nothing to install.
A signature covers the patch's hash, so a patch edited after signing no longer
matches and is refused.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PARTIES = ("vendor", "customer")
NAMESPACE = "twokey"


class Refused(Exception):
    """A rule of the two-key gate said no."""


def home() -> Path:
    return Path(os.environ.get("TWOKEY_HOME", Path.cwd() / ".twokey"))


def target() -> Path:
    return Path(os.environ.get("TWOKEY_TARGET", Path.cwd() / "service"))


def key_path(party: str) -> Path:
    return home() / "keys" / party


def state_path() -> Path:
    return home() / "change.json"


def ledger_path() -> Path:
    return home() / "ledger.jsonl"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_ledger() -> list[dict]:
    if not ledger_path().exists():
        return []
    return [json.loads(line) for line in ledger_path().read_text().splitlines() if line]


def entry_hash(entry: dict) -> str:
    body = {key: value for key, value in entry.items() if key != "hash"}
    return sha256(json.dumps(body, sort_keys=True).encode())


def record(event: str, **fields: object) -> dict:
    """Append to the ledger. Each entry carries the hash of the one before it."""
    entries = read_ledger()
    entry = {
        "seq": len(entries) + 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        **fields,
        "prev": entries[-1]["hash"] if entries else "",
    }
    entry["hash"] = entry_hash(entry)
    with ledger_path().open("a") as ledger:
        ledger.write(json.dumps(entry) + "\n")
    return entry


def open_change() -> dict:
    if not state_path().exists():
        raise Refused("There is no open change. Propose one first.")
    change = json.loads(state_path().read_text())
    if change["state"] != "open":
        raise Refused(f"Change {change['id']} is already {change['state']}.")
    return change


def save(change: dict) -> None:
    state_path().write_text(json.dumps(change, indent=2))


def statement(change: dict) -> bytes:
    """The exact bytes each party signs."""
    return f"{change['id']}\n{change['patch_sha256']}\n".encode()


def sign(party: str, change: dict) -> str:
    with tempfile.TemporaryDirectory() as folder:
        message = Path(folder) / "statement"
        message.write_bytes(statement(change))
        subprocess.run(
            ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key_path(party)),
             "-n", NAMESPACE, str(message)],
            check=True, capture_output=True,
        )
        return Path(f"{message}.sig").read_text()


def verifies(party: str, change: dict, signature: str) -> bool:
    public = key_path(party).with_suffix(".pub").read_text().strip()
    with tempfile.TemporaryDirectory() as folder:
        allowed = Path(folder) / "allowed"
        allowed.write_text(f"{party} {public}\n")
        sig = Path(folder) / "sig"
        sig.write_text(signature)
        checked = subprocess.run(
            ["ssh-keygen", "-q", "-Y", "verify", "-f", str(allowed), "-I", party,
             "-n", NAMESPACE, "-s", str(sig)],
            input=statement(change), capture_output=True,
        )
    return checked.returncode == 0


def check_patch_unchanged(change: dict) -> None:
    found = sha256(Path(change["patch_path"]).read_bytes())
    if found != change["patch_sha256"]:
        record("refused", change=change["id"], reason="patch changed", found=found)
        raise Refused(
            f"Change {change['id']} refused: the patch is not the one proposed "
            f"({change['patch_sha256'][:12]} expected, {found[:12]} found)."
        )


def apply_change(change: dict) -> None:
    for party in PARTIES:
        if not verifies(party, change, change["signatures"][party]):
            record("refused", change=change["id"], reason=f"bad {party} signature")
            raise Refused(f"Change {change['id']} refused: {party}'s signature is invalid.")
    done = subprocess.run(
        ["patch", "-p1", "--forward", "--batch", "-d", str(target()),
         "-i", change["patch_path"]],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        record("failed", change=change["id"], output=done.stdout[-400:])
        raise Refused(f"Both keys turned but the patch did not apply:\n{done.stdout}")
    change["state"] = "applied"
    save(change)
    record("applied", change=change["id"], patch_sha256=change["patch_sha256"])
    print(f"Both keys turned. Change {change['id']} applied.")


def cmd_init(_: argparse.Namespace) -> None:
    (home() / "keys").mkdir(parents=True, exist_ok=True)
    (home() / "patches").mkdir(exist_ok=True)
    for party in PARTIES:
        if not key_path(party).exists():
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", party,
                 "-f", str(key_path(party))],
                check=True,
            )
    print(f"Keys ready in {home() / 'keys'}.")


def cmd_propose(args: argparse.Namespace) -> None:
    propose(Path(args.patch).read_bytes(), args.summary)


def cmd_ship(args: argparse.Namespace) -> None:
    """Open a change from the patch on stdin and turn the vendor's key on it.

    One command, so the approval a person gives shows the exact patch they sign."""
    propose(sys.stdin.buffer.read(), args.summary)
    turn("vendor")


def propose(data: bytes, summary: str) -> None:
    if state_path().exists():
        current = json.loads(state_path().read_text())
        if current["state"] == "open":
            raise Refused(f"Change {current['id']} is still open.")
    if not data.strip():
        raise Refused("The patch is empty.")
    number = sum(1 for entry in read_ledger() if entry["event"] == "proposed") + 1
    change_id = f"CHG-{number:03d}"
    stored = home() / "patches" / f"{change_id}.patch"
    stored.write_bytes(data)
    change = {
        "id": change_id,
        "summary": summary,
        "patch_path": str(stored),
        "patch_sha256": sha256(data),
        "state": "open",
        "signatures": {},
    }
    save(change)
    record("proposed", change=change_id, summary=summary,
           patch_sha256=change["patch_sha256"])
    print(f"{change_id} opened for patch {change['patch_sha256'][:12]}. Waiting for two keys.")


def cmd_turn(args: argparse.Namespace) -> None:
    turn(args.party)


def turn(party: str) -> None:
    change = open_change()
    check_patch_unchanged(change)
    if party in change["signatures"]:
        raise Refused(f"The {party} key is already turned on {change['id']}.")
    change["signatures"][party] = sign(party, change)
    save(change)
    record("key_turned", change=change["id"], party=party,
           patch_sha256=change["patch_sha256"])
    waiting = [other for other in PARTIES if other not in change["signatures"]]
    if waiting:
        print(f"{party} key turned on {change['id']}. Waiting for {waiting[0]}.")
        return
    apply_change(change)


def cmd_status(_: argparse.Namespace) -> None:
    if not state_path().exists():
        print("No change yet.")
        return
    change = json.loads(state_path().read_text())
    turned = ", ".join(change["signatures"]) or "none"
    print(f"{change['id']} [{change['state']}] {change['summary']}")
    print(f"patch {change['patch_sha256'][:12]}, keys turned: {turned}")


def cmd_audit(_: argparse.Namespace) -> None:
    previous = ""
    entries = read_ledger()
    for entry in entries:
        if entry["prev"] != previous or entry_hash(entry) != entry["hash"]:
            raise Refused(f"Ledger broken at entry {entry['seq']}.")
        previous = entry["hash"]
    print(f"Ledger intact: {len(entries)} entries.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="twokey", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(run=cmd_init)
    propose_parser = commands.add_parser("propose")
    propose_parser.add_argument("patch")
    propose_parser.add_argument("-s", "--summary", required=True)
    propose_parser.set_defaults(run=cmd_propose)
    ship = commands.add_parser("ship")
    ship.add_argument("-s", "--summary", required=True)
    ship.set_defaults(run=cmd_ship)
    turn_parser = commands.add_parser("turn")
    turn_parser.add_argument("party", choices=PARTIES)
    turn_parser.set_defaults(run=cmd_turn)
    commands.add_parser("status").set_defaults(run=cmd_status)
    commands.add_parser("audit").set_defaults(run=cmd_audit)
    args = parser.parse_args()
    try:
        args.run(args)
    except Refused as refused:
        print(f"REFUSED: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
