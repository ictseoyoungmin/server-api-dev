#!/usr/bin/env bash
set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-pet_instances_v1}"
HAS_JQ=0
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
fi

print_json() {
  local body="$1"
  if [[ "${HAS_JQ}" -eq 1 ]]; then
    echo "${body}" | jq .
  else
    echo "${body}"
  fi
}

is_qdrant_ok() {
  local body="$1"
  python3 - "$body" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print("invalid_json")
    sys.exit(2)

status = data.get("status")
if isinstance(status, dict) and status.get("error"):
    print(status.get("error"))
    sys.exit(1)

if isinstance(status, str) and status.lower() in {"ok", "acknowledged"}:
    print("ok")
    sys.exit(0)

result = data.get("result")
if isinstance(result, bool):
    print("ok" if result else "result_false")
    sys.exit(0 if result else 1)

# Fallback: treat unknown success-like payload as ok when no explicit error exists.
print("ok")
sys.exit(0)
PY
}

if [[ "${1:-}" == "--hard" ]]; then
  echo "[WARN] Deleting collection: ${QDRANT_COLLECTION}"
  resp="$(curl -sS -X DELETE "${QDRANT_URL}/collections/${QDRANT_COLLECTION}" || true)"
  print_json "${resp}"
  if msg="$(is_qdrant_ok "${resp}" 2>/dev/null)"; then
    echo "[OK] Collection deleted. It will be recreated on next API start."
    exit 0
  fi
  echo "[FAIL] Collection delete failed: ${msg}"
  exit 1
fi

echo "[INFO] Soft clear: deleting all points in collection '${QDRANT_COLLECTION}'"
read -r -p "Proceed? (y/N): " ans
if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
  echo "Aborted."
  exit 1
fi

resp="$(curl -sS -X POST "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/delete" \
  -H 'Content-Type: application/json' \
  -d '{"filter": {"must": []}, "wait": true}' || true)"
print_json "${resp}"
if msg="$(is_qdrant_ok "${resp}" 2>/dev/null)"; then
  echo "[OK] All points deleted."
  exit 0
fi
echo "[FAIL] Point delete failed: ${msg}"
exit 1
