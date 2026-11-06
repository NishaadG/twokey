#!/usr/bin/env bash
# Try the two-key gate in about a minute, with no chat apps and no accounts:
#   ./scripts/try.sh
# You play both companies. It runs the real gate, the real signatures and the
# real board, and then tries to cheat it. TWOKEY_AUTO=1 runs it without pauses.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

for tool in python3 ssh-keygen patch curl; do
  command -v "$tool" >/dev/null || { echo "This needs $tool."; exit 1; }
done
for port in 8099 8787; do
  if curl -s -o /dev/null -m 1 "http://127.0.0.1:$port/"; then
    echo "Port $port is already in use. Stop what's using it, then try again."
    exit 1
  fi
done

WORK="$(mktemp -d)"
PIDS=()
finish() {
  [ "${#PIDS[@]}" -gt 0 ] && kill "${PIDS[@]}" 2>/dev/null || true
  rm -rf "$WORK"
}
trap finish EXIT

export TWOKEY_HOME="$WORK/gate" TWOKEY_TARGET="$WORK/service"
twokey() { python3 "$REPO/twokey/twokey.py" "$@"; }
say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
next() {
  if [ "${TWOKEY_AUTO:-}" = "1" ]; then
    sleep "${TWOKEY_PAUSE:-3}"
  else
    read -r -p "Press Enter to continue. "
  fi
}
quote() {
  printf 'Orders API answers: %s\n' \
    "$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8099/quote?items=3')"
}

cp -r "$REPO/service" "$WORK/service"
twokey init >/dev/null
(cd "$WORK/service" && exec python3 orders_api.py >/dev/null 2>&1) &
PIDS+=($!)
python3 "$REPO/dashboard/server.py" >/dev/null 2>&1 &
PIDS+=($!)
sleep 1

say "TwoKey: nothing reaches production until both companies turn their key."
echo "Open the board to watch it live: http://127.0.0.1:8787"
echo
echo "A vendor's bad release has taken down a customer's orders API."
quote
next

mkdir -p "$WORK/diff/a" "$WORK/diff/b"
cp "$WORK/service/pricing.json" "$WORK/diff/a/pricing.json"
python3 - "$WORK" <<'FIX'
import json, sys
from pathlib import Path
work = Path(sys.argv[1])
rules = json.loads((work / "service/pricing.json").read_text())
rules["bulk_discount_percent"] = 15
rules["version"] = "2.4.2"
(work / "diff/b/pricing.json").write_text(json.dumps(rules, indent=2) + "\n")
FIX
(cd "$WORK/diff" && diff -u a/pricing.json b/pricing.json || true) > "$WORK/fix.patch"

say "The vendor writes the fix and turns the first key."
twokey ship -s "Release 2.4.2: bulk_discount_percent as a number" < "$WORK/fix.patch"
quote
echo "One key changes nothing."
next

PATCH="$TWOKEY_HOME/patches/CHG-001.patch"
cp "$PATCH" "$WORK/patch.saved"
say "Someone slips a different discount into the signed patch."
python3 - "$PATCH" <<'CHEAT'
import sys
from pathlib import Path
patch = Path(sys.argv[1])
patch.write_text(patch.read_text().replace('"bulk_discount_percent": 15', '"bulk_discount_percent": 90'))
CHEAT
twokey turn customer || true
quote
echo "The gate refused it: the signature covers the exact patch."
cp "$WORK/patch.saved" "$PATCH"
next

say "The customer turns the second key on the real patch."
twokey turn customer
quote
next

LEDGER="$TWOKEY_HOME/ledger.jsonl"
cp "$LEDGER" "$WORK/ledger.saved"
say "Afterwards, someone rewrites history in the ledger."
python3 - "$LEDGER" <<'REWRITE'
import sys
from pathlib import Path
ledger = Path(sys.argv[1])
ledger.write_text(ledger.read_text().replace('"party": "customer"', '"party": "vendor"', 1))
REWRITE
twokey audit || true
cp "$WORK/ledger.saved" "$LEDGER"
echo "Put back:"
twokey audit
next

say "That's the gate. In the full version each key is a person pressing a button in their own chat app."
echo "Setup for that is in the README."
if [ "${TWOKEY_AUTO:-}" != "1" ]; then
  read -r -p "Press Enter to stop the board and clean up. "
fi
