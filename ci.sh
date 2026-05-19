#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Planner CI ==="
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. Lint check (syntax only)
echo "[1/3] Syntax check..."
python3 -m py_compile jm/main.py
python3 -m py_compile my/main.py
python3 -m py_compile work/main.py
python3 -m py_compile hub/main.py
for f in common/*.py; do
    python3 -m py_compile "$f"
done
echo "       All files compile OK"

# 2. Tests
echo "[2/3] Running tests..."
python3 -m pytest tests/ -v --tb=short 2>&1
TEST_EXIT=$?

# 3. Summary
echo ""
echo "[3/3] Summary"
echo "       Syntax:  OK"
if [ $TEST_EXIT -eq 0 ]; then
    echo "       Tests:   PASSED"
else
    echo "       Tests:   FAILED"
    exit 1
fi

echo ""
echo "=== CI PASSED ==="
