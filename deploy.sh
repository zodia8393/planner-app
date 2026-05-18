#!/bin/bash
# Deploy a planner app to Fly.io, bundling common/ into the build context
set -e

APP="$1"
if [ -z "$APP" ] || [ ! -d "$APP" ]; then
    echo "Usage: ./deploy.sh <jm|my|work>"
    exit 1
fi

shift
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/$APP"

cp -r "$SCRIPT_DIR/common" "$APP_DIR/common"
trap 'rm -rf "$APP_DIR/common"' EXIT

cd "$APP_DIR"
~/.fly/bin/flyctl deploy --remote-only "$@"
