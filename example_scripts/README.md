# Example scripts (Qdrant PoC)

Defaults assume the API is running at http://localhost:8001.
Set `API_BASE` if different.

Quick start (real sample paths in /workspace/PoC):
- `bash 01_embed.sh` (defaults to `/workspace/PoC/dogface_fastapi_poc/test_images/a.png`)
- `bash 02_embed_batch.sh` (defaults to `a.png` + `images.jpg`)
- `bash 03_ingest.sh` (defaults to `/workspace/PoC/dogface_fastapi_poc/test_images/images.jpg`)
- `bash 04_search.sh` (auto-uses last ingest instance_id if available)
- `bash 05_labels.sh` (auto-uses last ingest instance_id if available)

Notes:
- `04_search.sh` expects `QUERY_INSTANCE_IDS_JSON` as a JSON array string, e.g.
  `QUERY_INSTANCE_IDS_JSON='["ins_123","ins_456"]'`
- `05_labels.sh` needs a real `INSTANCE_ID` from ingest results.
- `03_ingest.sh` saves the last response to `example_scripts/last_ingest.json`.
