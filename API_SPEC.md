# API Spec (PoC)

Related design:
- `SEMI_AUTO_CLASSIFICATION_DESIGN.md` (semi-auto daycare workflow extension plan)

Base URL (default):
- Scripted run: `http://<host>:8001` (see `run_api.sh`)
- Docker Compose: `http://<host>:8000` (see `docker-compose.yml`)

## 1) Health
`GET /v1/health`

## 2) Ingest (upload → detect → embed → store)
`POST /v1/ingest`

**Content-Type**: `multipart/form-data`

Fields:
- `file` (required) : image
- `daycare_id` (required) : string
- `trainer_id` (optional) : string
- `captured_at` (optional) : ISO8601 string (e.g. `2026-01-31T09:10:11Z`)

Query:
- `include_embedding` (optional, default false)

Response:
- `image`: `image_id`, `storage_path`, `width/height`, timestamps
- `instances[]`: per detected instance: `instance_id`, `class_id`, `species`, `confidence`, `bbox`
  - `embedding` is included only when `include_embedding=true`
  - `embedding_meta` is included when an embedding is present

## 3) Search (gallery ordering)
`POST /v1/search`

**Content-Type**: `application/json`

Request:
```json
{
  "daycare_id": "dc_001",
  "query": {"instance_ids": ["ins_..."], "merge": "RRF"},
  "filters": {"species": "DOG"},
  "top_k_images": 200,
  "per_query_limit": 400
}
```

Response:
```json
{
  "query_debug": {"used_vectors": 1, "merge": "RRF"},
  "results": [
    {
      "image_id": "img_...",
      "score": 0.1234,
      "best_match": {
        "instance_id": "ins_...",
        "bbox": {"x1":0.1,"y1":0.2,"x2":0.5,"y2":0.9},
        "score": 0.81
      }
    }
  ]
}
```

Notes:
- `results[].score` is the ranking score. With `merge=MAX`, it equals the best cosine similarity.
- `results[].best_match.score` is always the best cosine similarity.

## 4) Labels (instance_id → pet_id)
`POST /v1/labels`

**Content-Type**: `application/json`

```json
{
  "daycare_id": "dc_001",
  "assignments": [
    {
      "instance_id": "ins_...",
      "action": "ACCEPT",
      "pet_id": "pet_aaa",
      "source": "MANUAL",
      "confidence": 1.0
    }
  ]
}
```

For this PoC, labels are stored in Qdrant payload (`pet_id`, `label_source`, etc.).
`action`:
- `ACCEPT`: requires `pet_id`, writes `assignment_status=ACCEPTED`
- `REJECT`: clears `pet_id`, writes `assignment_status=REJECTED`
- `CLEAR`: clears decision, writes `assignment_status=UNREVIEWED`

Note:
- Label updates also sync corresponding local sidecar meta JSON instance fields.
- `daycare_id` is currently accepted in the request but not enforced server-side for label writes.

## 5) Images (gallery)
`GET /v1/images`

Query:
- `daycare_id` (required)
- `date` (optional): `YYYY-MM-DD` (UTC date filter)
- `tab` (optional): `ALL | UNCLASSIFIED | PET` (default `ALL`)
- `pet_id` (required when `tab=PET`)
- `limit` (optional, default 200)
- `offset` (optional, default 0)

Response:
- `items[]`: `image_id`, `raw_url`, `thumb_url`, timestamps, etc.

`GET /v1/images/{image_id}?variant=raw|thumb`

`GET /v1/images/{image_id}/meta`
Returns image meta + detected instances (bbox, class_id, etc.).
Note:
- Image/instance metadata is read from local JSON sidecars created at ingest time.
- Label updates via `/v1/labels` are written to Qdrant payload and mirrored to these JSON sidecars.

## 5.0) Pets (for PET tab selector)
`GET /v1/pets`

Query:
- `daycare_id` (required)

Response:
- `items[]`: `pet_id`, `pet_name`, `image_count`, `instance_count`

Notes:
- Primary source is labeled instances in `storage_dir/meta/*.json` filtered by `daycare_id`.
- `pet_name` is resolved from `storage_dir/pets/{pet_id}/{pet_name}` when available.
- For PoC fallback, pets existing under `storage_dir/pets` are included even if counts are zero.

## 5.1) Auto Classification (date scope)
`POST /v1/classify/auto`

**Content-Type**: `application/json`

```json
{
  "daycare_id": "dc_001",
  "date": "2026-02-13",
  "auto_accept_threshold": 0.78,
  "candidate_threshold": 0.62,
  "search_limit": 200,
  "dry_run": false
}
```

Behavior:
- Target: instances on the given date that are not `assignment_status=ACCEPTED` and have no `pet_id`.
- Exemplar pool: labeled instances in the same daycare (`pet_id` exists; `assignment_status` is empty or `ACCEPTED`).
- Decision:
  - `score >= auto_accept_threshold`: write `pet_id`, `assignment_status=ACCEPTED`
  - `candidate_threshold <= score < auto_accept_threshold`: write candidate only (`auto_pet_id`, `assignment_status=UNREVIEWED`)
  - below threshold: keep `UNREVIEWED`
- When `dry_run=true`, no payload/sidecar updates are written.

## 5.2) Similar Search In Current Tab
`POST /v1/classify/similar`

**Content-Type**: `application/json`

```json
{
  "daycare_id": "dc_001",
  "date": "2026-02-13",
  "tab": "UNCLASSIFIED",
  "query_instance_ids": ["ins_..."],
  "merge": "RRF",
  "top_k_images": 200,
  "per_query_limit": 400
}
```

Behavior:
- Uses the selected query instances as exemplars.
- Candidate set is restricted to images currently visible in tab scope:
  - `ALL`
  - `UNCLASSIFIED`
  - `PET` (`pet_id` required)
- Returns tab-local image ranking by similarity score.
- Each result also includes `raw_url` and `thumb_url` for direct gallery rendering.

## 5.3) Finalize Daily Buckets
`POST /v1/buckets/finalize`

**Content-Type**: `application/json`

```json
{
  "daycare_id": "dc_001",
  "date": "2026-02-13",
  "pet_ids": ["pet_a", "pet_b"]
}
```

Behavior:
- Scans accepted assignments (`assignment_status=ACCEPTED`) on that day.
- Builds `pet_id -> image_ids[]` mapping.
- Persists manifest JSON under:
  - `storage_dir/buckets/{daycare_id}/{YYYY-MM-DD}/finalize_*.json`
- Response/manifest includes `quality_metrics`:
  - `total_day_images`, `unclassified_images`, `unclassified_image_ratio`
  - `total_instances`, `accepted_instances`, `accepted_auto_instances`
  - `unreviewed_instances`, `rejected_instances`, `auto_accept_ratio`

`GET /v1/buckets/{daycare_id}/{day}`

Query:
- `manifest` (optional): explicit manifest filename. If omitted, latest manifest is returned.

## 6) Embed (single image, no DB write)
`POST /v1/embed`

**Content-Type**: `multipart/form-data`

Fields:
- `file` (required) : image

Query:
- `format` (optional): `json|f32|f16` (default from server settings)

Response (JSON format):
```json
{
  "model_version": "miewid",
  "dim": 1024,
  "embedding": [0.0123, -0.0456, ...]
}
```

Notes:
- JSON response contains L2-normalized float32 values.
- Binary response (`f32`/`f16`) returns raw bytes with headers:
  - `X-Embedding-Dim`, `X-Embedding-DType`, `X-Model-Version`

## 7) Embed (batch, no DB write)
`POST /v1/embed/batch`

**Content-Type**: `multipart/form-data`

Fields:
- `files` (required, repeated) : images

Query:
- `format` (optional): `json|f32|f16` (default from server settings)

Response (JSON format):
```json
{
  "model_version": "miewid",
  "dim": 1024,
  "items": [
    {"filename": "a.jpg", "embedding": [0.01, -0.02, ...]},
    {"filename": "b.jpg", "embedding": [0.03, -0.04, ...]}
  ]
}
```

Notes:
- Binary response is a framed format `dogface-batch-v1`:
  - `uint32 N`, `uint32 D`, `uint8 dtype_code (1=float32, 2=float16)`, then `N*D` values.
- Headers include `X-Embedding-Count`, `X-Embedding-Dim`, `X-Embedding-DType`, `X-Model-Version`, `X-Batch-Format`.

## 8) Sync Facebank Images (hash-based dedupe)
`GET /v1/sync-images`

Query:
- `petId` (required)
- `petName` (optional): name used for server-side folder grouping
- `facebankId` (required)
- `facebankVersion` (optional, default latest)
- `hashes` (required): CSV list of sha256 hashes

Response:
```json
{"existing_hashes": ["hash1", "hash3"]}
```

`POST /v1/sync-images`

**Content-Type**: `multipart/form-data`

Fields:
- `petId` (required)
- `petName` (required)
- `facebankId` (required)
- `facebankVersion` (required, int)
- `images` (required, repeated): image files
- `hashes` (required, repeated): sha256 for each image
- `modelVersion` (optional)
- `embeddingDim` (optional, int)
- `threshold` (optional, float)
- `deviceId` (optional)
- `createdAt` (optional, ISO8601)

Response:
```json
{
  "pet_id": "pet_123",
  "facebank_id": "fb_abc",
  "facebank_version": 2,
  "received": 5,
  "skipped": 2,
  "stored": 3,
  "existing_hashes": ["hash1", "hash3"],
  "model_version": "miewid",
  "embedding_dim": 1024,
  "threshold": 0.42,
  "device_id": "pixel8"
}
```

Storage (PoC):
- `storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/images/*`
- `storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/hash_index.json`
- `storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/facebank_meta.json`

## 9) Verification Trials (TP/FP/FN/TN logging)
`POST /v1/trials`

**Content-Type**: `multipart/form-data`

Fields:
- `id` (required): trial UUID (idempotency key)
- `petId` (required)
- `petName` (optional): name used for server-side folder grouping
- `facebankId` (required)
- `facebankVersion` (required, int)
- `score` (required, float)
- `isSuccess` (required, bool)
- `userFeedback` (required, bool)
- `timestamp` (optional, ISO8601)
- `pose` (optional, string)
- `trialImage` (required): image file

Response:
```json
{
  "trial_id": "trial_uuid",
  "status": "stored",
  "stored": true,
  "storage_path": "data/trials/2026-02-06/trial_uuid.json",
  "outcome": "TP"
}
```

Storage (PoC):
- `storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.json`
- `storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.jpg`
