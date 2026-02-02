#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8001}"
FORMAT="${FORMAT:-json}"
IMG="${IMG:-}"
DEFAULT_IMG="/workspace/PoC/dogface_fastapi_poc/test_images/a.png"

if [ -z "${IMG}" ] && [ -f "${DEFAULT_IMG}" ]; then
  IMG="${DEFAULT_IMG}"
fi

if [ -z "${IMG}" ] || [ ! -f "${IMG}" ]; then
  echo "Usage: IMG=/path/to.jpg $0" >&2
  echo "Hint: set IMG, or place a file at ${DEFAULT_IMG}" >&2
  exit 1
fi

curl -sS -X POST "${API_BASE}/v1/embed?format=${FORMAT}" \
  -F "file=@${IMG}" | cat
