#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

echo "[gradio-demo] root=$ROOT_DIR"
echo "[gradio-demo] API_BASE=${API_BASE:-http://localhost:8001}"

action_python="${PYTHON_BIN:-python3}"
"$action_python" example_scripts/gradio_demo/app.py
