# Example scripts (Qdrant PoC)

Defaults assume the API is running at http://localhost:8001.
Set `API_BASE` if different.

Quick start (real sample paths in /workspace/PoC):
- `bash 01_embed.sh` (defaults to `/workspace/PoC/dogface_fastapi_poc/test_images/a.png`)
- `bash 02_embed_batch.sh` (defaults to `a.png` + `images.jpg`)
- `bash 03_ingest.sh` (defaults to `/workspace/PoC/dogface_fastapi_poc/test_images/images.jpg`)
- `bash 04_search.sh` (auto-uses last ingest instance_id if available)
- `bash 05_labels.sh` (auto-uses last ingest instance_id if available)
- `bash 07_classification_smoke.sh` (auto/similar/finalize/get buckets smoke test)
- `bash 08_e2e_registered_unlabeled.sh` (registered 라벨링 + unlabeled ingest + auto/finalize E2E)
- `bash 09_verify_after_e2e.sh` (pets/images/buckets/meta 점검 리포트)
- `bash 10_reset_and_reseed_e2e.sh` (Qdrant+로컬저장소 초기화 후 08/09 연속 실행)
- `bash gradio_demo/run_gradio_demo.sh` (웹 UI로 반자동 흐름 검증)

Notes:
- `04_search.sh` expects `QUERY_INSTANCE_IDS_JSON` as a JSON array string, e.g.
  `QUERY_INSTANCE_IDS_JSON='["ins_123","ins_456"]'`
- `05_labels.sh` needs a real `INSTANCE_ID` from ingest results.
- `03_ingest.sh` saves the last response to `example_scripts/last_ingest.json`.
- `07_classification_smoke.sh` auto-reads `INSTANCE_ID` + `DAY` from `last_ingest.json` when present.
- `08_e2e_registered_unlabeled.sh` expects:
  - `data/images_for_test/{DAYCARE_ID}/registered/{pet_id}/*`
  - `data/images_for_test/{DAYCARE_ID}/{DAY}/unlabeled/**`
  - Optional readable naming: `registered/{pet_id}__{pet_name}/*`
    - Example: `registered/pet_001__뽀미/*`
    - Script parses `pet_id` for labeling and creates `data/pets/{pet_id}/{pet_name}` for display mapping.
- `09_verify_after_e2e.sh` verifies:
  - `/v1/pets`
  - `/v1/images` (`ALL`, `UNCLASSIFIED`, `PET` per pet)
  - `/v1/buckets/{daycare_id}/{day}`
  - sample `/v1/images/{image_id}/meta`
- `10_reset_and_reseed_e2e.sh` notes:
  - 테스트 데이터를 완전히 초기화하므로 중복 UI 점검 전에 권장.
  - `DAYCARE_ID`, `DAY` 미지정 시 `data/images_for_test`에서 자동 감지:
    - `DAYCARE_ID`: 첫 번째 하위 폴더
    - `DAY`: `YYYY-MM-DD` 형식 폴더 중 최신값
  - 기본은 Qdrant points만 삭제 (`HARD_COLLECTION_RESET=0`), 컬렉션 삭제는 `HARD_COLLECTION_RESET=1`.
  - 컬렉션이 없으면 `/v1/health`의 `model.dim`을 사용해 자동 재생성.
    - 필요 시 수동 지정: `QDRANT_VECTOR_DIM=2152`
  - 로컬에서 아래 디렉터리를 비우고 재생성:
    - `data/images`, `data/thumbs`, `data/meta`, `data/pets`, `data/buckets`, `data/trials`
  - 비대화식 실행:
    - `FORCE=1 bash 10_reset_and_reseed_e2e.sh`
  - 데이터 루트 변경:
    - `DATA_TEST_ROOT=/path/to/images_for_test FORCE=1 bash 10_reset_and_reseed_e2e.sh`
