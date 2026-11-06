#!/usr/bin/env bash
# Set up or reset the lab on the machine the agents run on: ./scripts/lab.sh
# Starts Harborline's orders API with the bad vendor release, and clears any change.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LAB="${TWOKEY_LAB:-$HOME/workspace/twokey-lab}"

mkdir -p "$LAB/bin" "$LAB/harborline/logs" "$LAB/quillpay"
pkill -f '[o]rders_api.py' || true
pkill -f '[o]rders-probe' || true
rm -rf "$LAB/harborline/service" "$LAB/state" "$LAB/harborline/twokey" "$LAB/harborline/logs/orders.log"
cp -r "$REPO/service" "$LAB/harborline/service"
cp "$REPO/twokey/twokey.py" "$LAB/bin/twokey.py"
cp "$REPO/agents/release-notes.md" "$LAB/quillpay/release-notes.md"
cp "$REPO/service/pricing.json" "$LAB/quillpay/pricing.json"
rm -f "$LAB/quillpay/"*.patch

cat > "$LAB/bin/twokey" <<EOF
#!/usr/bin/env bash
export TWOKEY_HOME="$LAB/harborline/twokey" TWOKEY_TARGET="$LAB/harborline/service"
exec python3 "$LAB/bin/twokey.py" "\$@"
EOF
chmod +x "$LAB/bin/twokey"
"$LAB/bin/twokey" init

cd "$LAB/harborline/service"
nohup python3 orders_api.py >> "$LAB/harborline/logs/orders.log" 2>&1 &
sleep 1
# Customers' traffic: a quote every few seconds, so the log shows what they see.
nohup bash -c 'exec -a orders-probe bash -c "while true; do curl -s -o /dev/null \"http://127.0.0.1:8099/quote?items=3\"; sleep 4; done"' >/dev/null 2>&1 &
echo "Orders API: $(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8099/quote?items=3') on /quote (500 is the incident)"
