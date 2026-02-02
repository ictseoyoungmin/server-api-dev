#!/usr/bin/env bash
set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-pet_instances_v1}"
HAS_JQ=0
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
fi

if [[ "${1:-}" == "--hard" ]]; then
  echo "[WARN] Deleting collection: ${QDRANT_COLLECTION}"
  if [[ "${HAS_JQ}" -eq 1 ]]; then
    curl -sS -X DELETE "${QDRANT_URL}/collections/${QDRANT_COLLECTION}" | jq .
  else
    curl -sS -X DELETE "${QDRANT_URL}/collections/${QDRANT_COLLECTION}"
  fi
  echo "[OK] Collection deleted. It will be recreated on next API start."
  exit 0
fi

echo "[INFO] Soft clear: deleting all points in collection '${QDRANT_COLLECTION}'"
read -r -p "Proceed? (y/N): " ans
if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
  echo "Aborted."
  exit 1
fi

if [[ "${HAS_JQ}" -eq 1 ]]; then
  curl -sS -X POST "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/delete" \
    -H 'Content-Type: application/json' \
    -d '{"filter": {"must": []}, "wait": true}' | jq .
else
  curl -sS -X POST "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/points/delete" \
    -H 'Content-Type: application/json' \
    -d '{"filter": {"must": []}, "wait": true}'
fi

echo "[OK] All points deleted."
