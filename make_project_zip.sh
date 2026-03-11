#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash make_project_zip.sh
#   bash make_project_zip.sh /path/to/output.zip
#
# This script zips the current project directory.
# You can edit EXCLUDE_PATTERNS below to exclude files/folders you don't want.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "${PROJECT_DIR}")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_OUTPUT="${PROJECT_DIR}/${PROJECT_NAME}_${TS}.zip"
OUTPUT_ZIP="${1:-${DEFAULT_OUTPUT}}"

if ! command -v zip >/dev/null 2>&1; then
  echo "error: 'zip' command not found. Install zip first."
  exit 1
fi

# Edit this list as you want.
# Pattern rule follows zip -x wildcard matching.
EXCLUDE_PATTERNS=(
  ".git/*"
  ".gitignore"
  ".envqd/*"
  "__pycache__/*"
  "*.pyc"
  "*.pyo"
  ".pytest_cache/*"
  ".mypy_cache/*"
  ".ruff_cache/*"
  ".DS_Store"
  "qdrant_storage/*"
  "data/*"
  "weights/*"
  "models_cache/*"
  "notebooks/*"
  "*.zip"
)

tmp_exclude_file="$(mktemp)"
cleanup() {
  rm -f "${tmp_exclude_file}"
}
trap cleanup EXIT

for p in "${EXCLUDE_PATTERNS[@]}"; do
  printf '%s\n' "${p}" >> "${tmp_exclude_file}"
done

pushd "${PROJECT_DIR}" >/dev/null
zip -r "${OUTPUT_ZIP}" . -x@"${tmp_exclude_file}"
popd >/dev/null

echo "created: ${OUTPUT_ZIP}"
echo "exclude patterns:"
for p in "${EXCLUDE_PATTERNS[@]}"; do
  echo "  - ${p}"
done
