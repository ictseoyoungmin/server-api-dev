# API Spec (PoC)

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
    {"instance_id": "ins_...", "pet_id": "pet_aaa", "source": "MANUAL", "confidence": 1.0}
  ]
}
```

For this PoC, labels are stored in Qdrant payload (`pet_id`, `label_source`, etc.).
Note:
- `daycare_id` is currently accepted in the request but not enforced server-side for label writes.

## 5) Images (gallery)
`GET /v1/images`

Query:
- `daycare_id` (required)
- `limit` (optional, default 200)
- `offset` (optional, default 0)

Response:
- `items[]`: `image_id`, `raw_url`, `thumb_url`, timestamps, etc.

`GET /v1/images/{image_id}?variant=raw|thumb`

`GET /v1/images/{image_id}/meta`
Returns image meta + detected instances (bbox, class_id, etc.).
Note:
- Image/instance metadata is read from local JSON sidecars created at ingest time.
- Label updates via `/v1/labels` are stored in Qdrant payload and are not reflected in these JSON sidecars.

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
