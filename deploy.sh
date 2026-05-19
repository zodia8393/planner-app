#!/bin/bash
# Deploy a planner app to Fly.io, bundling common/ into the build context
set -e

APP="$1"
if [ -z "$APP" ] || [ ! -d "$APP" ]; then
    echo "Usage: ./deploy.sh <jm|my|work> [--skip-tests] [flyctl args...]"
    exit 1
fi

shift
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/$APP"

# Run tests before deploy unless --skip-tests is passed
if [ "$1" = "--skip-tests" ]; then
    shift
else
    echo "==> Running tests before deploy..."
    cd "$SCRIPT_DIR"
    python3 -m pytest tests/ -q --tb=short
    echo "==> Tests passed, proceeding with deploy"
fi

cp -r "$SCRIPT_DIR/common" "$APP_DIR/common"
trap 'rm -rf "$APP_DIR/common"' EXIT

cd "$APP_DIR"
~/.fly/bin/flyctl deploy --remote-only "$@"
