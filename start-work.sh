#!/bin/bash
# Start Work planner on LAN (HTTPS, self-signed cert)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$SCRIPT_DIR/work"
WORK_PORT=8001
LAN_IP="192.168.0.29"

# Kill previous instance
pkill -f "uvicorn.*${WORK_PORT}" 2>/dev/null || true
sleep 1

# Start Work planner with HTTPS
echo "Work 플래너 시작 (HTTPS, port ${WORK_PORT})..."
cd "$WORK_DIR"
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port $WORK_PORT \
    --ssl-keyfile=key.pem --ssl-certfile=cert.pem &>/tmp/work-planner.log &
WORK_PID=$!

# Wait for server ready
for i in $(seq 1 10); do
    if curl -sk -o /dev/null https://localhost:${WORK_PORT}/health 2>/dev/null; then
        echo "✓ Work 플래너 정상 (PID: $WORK_PID)"
        break
    fi
    sleep 1
done

echo ""
echo "══════════════════════════════════"
echo "  https://${LAN_IP}:${WORK_PORT}"
echo "══════════════════════════════════"
echo ""
echo "첫 접속 시 '안전하지 않음' 경고 → 고급 → 계속 진행"
echo "PID: $WORK_PID | Log: /tmp/work-planner.log"
