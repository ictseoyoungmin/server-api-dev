#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/.envqd}"
REQ_FILE="${REQ_FILE:-${SCRIPT_DIR}/requirements.txt}"

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "requirements file not found: ${REQ_FILE}"
  exit 1
fi

python3 -m pip install --upgrade virtualenv

"${PYTHON_BIN}" -m virtualenv "${VENV_DIR}"

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel

"${VENV_DIR}/bin/python" -m pip install -r "${REQ_FILE}"

echo "venv ready: ${VENV_DIR}"
