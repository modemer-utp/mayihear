#!/usr/bin/env bash
# Usage: ./build-api.sh <GEMINI_API_KEY>
# Example: ./build-api.sh AIzaSyYOUR_KEY_HERE

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "ERROR: GEMINI_API_KEY argument is required."
    echo "Usage: $0 <GEMINI_API_KEY>"
    exit 1
fi

GEMINI_API_KEY="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$SCRIPT_DIR/../mayihear-api"
RUN_BUILT="$API_DIR/run_built.py"

echo "[build-api] Substituting API key into run_built.py..."
sed "s/__GEMINI_API_KEY_PLACEHOLDER__/${GEMINI_API_KEY}/g" \
    "$API_DIR/run.py" > "$RUN_BUILT"

echo "[build-api] Activating virtual environment..."
# shellcheck disable=SC1091
source "$API_DIR/.venv/bin/activate"

echo "[build-api] Running PyInstaller..."
cd "$API_DIR"
pyinstaller mayihear-api.spec --noconfirm
PYINSTALLER_EXIT=$?

echo "[build-api] Cleaning up run_built.py..."
rm -f "$RUN_BUILT"

deactivate || true

if [ $PYINSTALLER_EXIT -ne 0 ]; then
    echo "ERROR: PyInstaller failed with exit code $PYINSTALLER_EXIT"
    exit $PYINSTALLER_EXIT
fi

echo ""
echo "[build-api] Done. Binary at: mayihear-api/dist/mayihear-api/mayihear-api"
echo "[build-api] Verify: ./mayihear-api/dist/mayihear-api/mayihear-api & curl localhost:8000/health"
