#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001/v1}"
DAYCARE_ID="${DAYCARE_ID:-dc_001}"
TODAY_UTC="${TODAY_UTC:-$(date -u +%F)}"
SEED_ROOT="${SEED_ROOT:-/workspace/PoC/dogface_fastapi_poc_qdrant/data/images_for_test/dc_001/registered}"
DAILY_ROOT="${DAILY_ROOT:-/workspace/PoC/dogface_fastapi_poc_qdrant/data/images_for_test/dc_001/iphoneX/pictures/daily}"
UPDATED_BY="${UPDATED_BY:-scenario_runner}"
RESET_FIRST="${RESET_FIRST:-true}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLEAR_QDRANT_SCRIPT="${CLEAR_QDRANT_SCRIPT:-${SCRIPT_DIR}/06_clear_qdrant.sh}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing command: $1"; exit 1; }
}

require_cmd curl
require_cmd python3

if [[ "${RESET_FIRST}" == "true" ]]; then
  echo "[0/3] Reset storage outputs + Qdrant collection"
  if [[ ! -x "${CLEAR_QDRANT_SCRIPT}" ]]; then
    echo "clear script not executable: ${CLEAR_QDRANT_SCRIPT}"
    exit 1
  fi
  "${CLEAR_QDRANT_SCRIPT}" --hard

  rm -rf \
    "${PROJECT_ROOT}/data/meta" \
    "${PROJECT_ROOT}/data/images" \
    "${PROJECT_ROOT}/data/thumbs" \
    "${PROJECT_ROOT}/data/buckets"
  mkdir -p \
    "${PROJECT_ROOT}/data/meta" \
    "${PROJECT_ROOT}/data/images" \
    "${PROJECT_ROOT}/data/thumbs" \
    "${PROJECT_ROOT}/data/buckets"
fi

echo "[1/3] Seed folder upload"
if [[ ! -d "$SEED_ROOT" ]]; then
  echo "SEED_ROOT not found: $SEED_ROOT"
  echo "Expected structure: $SEED_ROOT/<pet_name>/*.{jpg,png,webp}"
  exit 1
fi

mapfile -t seed_files < <(find "$SEED_ROOT" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \) | sort)
if [[ ${#seed_files[@]} -eq 0 ]]; then
  echo "No seed images found under $SEED_ROOT"
  exit 1
fi

form_args=(
  -F "daycare_id=$DAYCARE_ID"
  -F "updated_by=$UPDATED_BY"
  -F "sync_label=true"
  -F "apply_to_all_instances=false"
  -F "skip_on_error=true"
)

for f in "${seed_files[@]}"; do
  rel="${f#${SEED_ROOT%/}/}"
  rel_with_root="$(basename "$SEED_ROOT")/$rel"
  form_args+=( -F "files=@$f" )
  form_args+=( -F "relative_paths=$rel_with_root" )
done

seed_resp="$(curl -sS -X POST "$BASE_URL/exemplars/upload-folder" "${form_args[@]}")"
echo "$seed_resp" | python3 -m json.tool >/tmp/seed_upload_only.json
seed_ok_count="$(python3 - <<'PY'
import json
with open('/tmp/seed_upload_only.json','r',encoding='utf-8') as f:
    d=json.load(f)
print(d.get('succeeded',0))
PY
)"
seed_fail_count="$(python3 - <<'PY'
import json
with open('/tmp/seed_upload_only.json','r',encoding='utf-8') as f:
    d=json.load(f)
print(d.get('failed',0))
PY
)"
echo "seed upload: succeeded=$seed_ok_count failed=$seed_fail_count"

echo "[2/3] Daily gallery ingest (no auto-classify)"
if [[ ! -d "$DAILY_ROOT" ]]; then
  echo "DAILY_ROOT not found: $DAILY_ROOT"
  echo "Expected flat gallery folder for test-only upload."
  exit 1
fi

mapfile -t daily_files < <(find "$DAILY_ROOT" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \) | sort)
if [[ ${#daily_files[@]} -eq 0 ]]; then
  echo "No daily images found under $DAILY_ROOT"
  exit 1
fi

ingested=0
for f in "${daily_files[@]}"; do
  ts="${TODAY_UTC}T09:00:00Z"
  curl -sS -X POST "$BASE_URL/ingest" \
    -F "file=@$f" \
    -F "daycare_id=$DAYCARE_ID" \
    -F "trainer_id=$UPDATED_BY" \
    -F "captured_at=$ts" \
    -F "image_role=DAILY" \
    >/tmp/ingest_upload_only_one.json
  ingested=$((ingested + 1))
done

echo "daily ingested: $ingested"
echo "[3/3] [DONE] Upload-only scenario complete."
echo "Now use emulator/app UI to run auto-classify manually."
