#!/bin/bash
# Start Work planner + cloudflared tunnel, register URL with Hub
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$SCRIPT_DIR/work"
HUB_URL="${HUB_URL:-http://localhost:8000}"
WORK_PORT=8001
TUNNEL_LOG="/tmp/cloudflared-work.log"

# Kill previous instances
pkill -f "uvicorn.*${WORK_PORT}" 2>/dev/null || true
pkill -f "cloudflared.*${WORK_PORT}" 2>/dev/null || true
sleep 1

# Start Work planner
echo "[1/3] Starting Work planner on port ${WORK_PORT}..."
cd "$WORK_DIR"
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port $WORK_PORT &>/tmp/work-planner.log &
WORK_PID=$!

# Wait for server ready
for i in $(seq 1 10); do
    if curl -s -o /dev/null http://localhost:${WORK_PORT}/health 2>/dev/null; then
        echo "       Work planner ready (PID: $WORK_PID)"
        break
    fi
    sleep 1
done

# Start cloudflared tunnel
echo "[2/3] Starting cloudflared tunnel..."
nohup cloudflared tunnel --url http://localhost:${WORK_PORT} &>"$TUNNEL_LOG" &
TUNNEL_PID=$!

# Wait for tunnel URL (cloudflared outputs it to stderr)
TUNNEL_URL=""
for i in $(seq 1 15); do
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    echo "       [WARN] Could not detect tunnel URL after 15s"
    echo "       Check $TUNNEL_LOG manually"
    exit 1
fi

echo "       Tunnel URL: $TUNNEL_URL"

# Register URL with Hub
echo "[3/3] Registering URL with Hub..."
RESP=$(curl -s -X POST "${HUB_URL}/update-work-url" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${TUNNEL_URL}\"}" 2>/dev/null || echo '{"ok":false}')

if echo "$RESP" | grep -q '"ok":true\|"ok": true'; then
    echo "       Registered with Hub"
else
    echo "       [WARN] Hub registration failed (Hub may not be running)"
    echo "       URL saved anyway — start Hub later to pick it up"
    # Save directly to Hub's data file as fallback
    mkdir -p "$SCRIPT_DIR/hub/data"
    echo "{\"work_url\": \"${TUNNEL_URL}\"}" > "$SCRIPT_DIR/hub/data/links.json"
fi

echo ""
echo "=== Work Planner Running ==="
echo "Local:  http://localhost:${WORK_PORT}"
echo "Public: ${TUNNEL_URL}"
echo "Hub:    ${HUB_URL}"
echo ""
echo "PIDs: work=$WORK_PID, tunnel=$TUNNEL_PID"
echo "Logs: /tmp/work-planner.log, $TUNNEL_LOG"
