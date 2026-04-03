# API Spec (PoC)

Related design:
- `SEMI_AUTO_CLASSIFICATION_DESIGN.md` (semi-auto classification workflow extension plan)

Base URL (default):
- Scripted run: `http://<host>:8001` (see `run_api.sh`)
- Docker Compose: `http://<host>:8000` (see `docker-compose.yml`)

## 0) Root
`GET /`

Response:
```json
{
  "name": "dogface-embedding-api",
  "docs": "/docs",
  "health": "/v1/health"
}
```

## 1) Health
`GET /v1/health`

`GET /v1/health/qdrant`

Response (example):
```json
{
  "status": "ok",
  "qdrant": {
    "collection": "pet_instances_v1",
    "points_count": 21,
    "total_images": 12,
    "sampled_vector_dim": 2152,
    "status": "green"
  }
}
```

Notes:
- `points_count` is the total Qdrant point count and is effectively the total instance count in this server.
- `total_images` is computed from `data/reid/meta/*.json`.
- `vectors_count` / `indexed_vectors_count` may be `null`/`0` on some Qdrant builds.

## 2) Ingest (upload → detect → embed → store)
`POST /v1/ingest`

**Content-Type**: `multipart/form-data`

Fields:
- `file` (required) : image
- `trainer_id` (optional) : string
- `captured_at` (optional) : ISO8601 string (e.g. `2026-01-31T09:10:11Z`)
- `image_role` (optional) : `DAILY|SEED` (default `DAILY`)
- `pet_name` (optional) : when `image_role=SEED`, used for subdirectory path

Query:
- `include_embedding` (optional, default false)

Response:
- `image`: `image_id`, `storage_path`, `width/height`, timestamps
- `instances[]`: per detected instance: `instance_id`, `class_id`, `species`, `confidence`, `bbox`
  - `embedding` is included only when `include_embedding=true`
  - `embedding_meta` is included when an embedding is present

Seed policy:
- When `image_role=SEED`, server stores only one instance per image (highest `confidence` detection).
- When `image_role=DAILY`, multi-instance ingest is preserved.

## 2.1) Identify (single-shot pet candidate lookup)
`POST /v1/identify`

**Content-Type**: `multipart/form-data`

Fields:
- `file` (required) : image
- `captured_at` (optional) : ISO8601 string
- `top_k` (optional, default `1`) : integer (`1..50`)

Response:
- `image_id`: ingested image id
- `instance_id`: representative detected instance id (highest `confidence`)
- `species`: detected species
- `bbox`: representative instance bbox
- `candidates[]`: top-k exemplar-based pet candidates
  - `pet_id`
  - `pet_name`
  - `score` (vector similarity score from Qdrant cosine search)

Response example:
```json
{
  "image_id": "img_xxx",
  "instance_id": "ins_xxx",
  "species": "DOG",
  "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.9},
  "candidates": [
    {
      "pet_id": "pet_pomi",
      "pet_name": "뽀미",
      "score": 0.91
    }
  ]
}
```

Notes:
- Internally this endpoint runs ingest first, then searches active exemplars (`is_seed=true`, `seed_active=true`) by vector similarity in the global exemplar pool.
- `captured_at` is optional. When omitted, server receive time is used and passed into ingest.
- This endpoint does not require a client-supplied `date`.
- If multiple instances are detected, only the highest-confidence instance is used for candidate search.

## 3) Search (gallery ordering)
`POST /v1/search`

**Content-Type**: `application/json`

Request:
```json
{
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
- For `filters.captured_from` / `filters.captured_to`, if timezone is omitted, server interprets them in business timezone (`settings.business_tz`, default `Asia/Seoul`).

Notes:
- `results[].score` is the ranking score. With `merge=MAX`, it equals the best cosine similarity.
- `results[].best_match.score` is always the best cosine similarity.

## 4) Labels (instance_id → pet_id)
`POST /v1/labels`

**Content-Type**: `application/json`

```json
{
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

## 5) Images (gallery)
`GET /v1/images`

Query:
- `date` (optional): `YYYY-MM-DD` (business timezone date filter; default `Asia/Seoul`)
- `tab` (optional): `ALL | UNCLASSIFIED | PET` (default `ALL`)
- `pet_id` (required when `tab=PET`)
- `include_seed` (optional, default `false`): seed(exemplar) 이미지 포함 여부
- `limit` (optional, default 200)
- `offset` (optional, default 0)

Response:
- `items[]`: `image_id`, `raw_url`, `thumb_url`, timestamps, `pet_ids[]`, etc.

`GET /v1/images/{image_id}?variant=raw|thumb`

`GET /v1/images/{image_id}/meta`
Returns image meta + detected instances (bbox, class_id, etc.).
Note:
- Image/instance metadata is read from local JSON sidecars created at ingest time.
- Label updates via `/v1/labels` are written to Qdrant payload and mirrored to these JSON sidecars.
- Physical storage is role-separated by `image_role`:
  - daily images: `storage_dir/images/daily/*`, `storage_dir/thumbs/daily/*`
  - seed(exemplar) images: `storage_dir/images/seed/{pet_name}/*`, `storage_dir/thumbs/seed/{pet_name}/*`

## 5.0) Pets (for PET tab selector)
`GET /v1/pets`

Response:
- `items[]`: `pet_id`, `pet_name`, `image_count`, `instance_count`

Notes:
- Primary source is Qdrant payload points aggregated globally across labeled and seed instances.
- `pet_name` is resolved from `reid_storage_dir/registry/pets.json` when available.

## 5.1) Exemplars (initial registration images)
`GET /v1/exemplars` (initial registration images)
`GET /v1/exemplars`

Query:
- `pet_id` (optional)
- `species` (optional)
- `active` (optional, default `true`)
- `q` (optional): substring search on `instance_id`, `image_id`, `note`, `pet_id`
- `limit`, `offset` (optional)

Response:
- `items[]`: `instance_id`, `pet_id`, `active`, `rank`, `note`, `created_at`, `updated_at`, `image_id`, ...

`POST /v1/exemplars`

Purpose:
- Register one or more instance IDs as initial exemplars for a pet.
- This API is intended for admin workflows (dashboard) and becomes the canonical source for auto-classifier exemplar pool.

`POST /v1/exemplars/upload`

Purpose:
- Convenience endpoint for admin dashboard.
- Supports two explicit modes:
  1) append mode: send `pet_id` to add one seed image to an existing pet
  2) create mode: send `pet_name` to create a new pet and register its first seed image

Behavior:
- Internally runs ingest first, then exemplar registration.
- `apply_to_all_instances=false` (default) registers only the highest-confidence instance.
- On success, response includes `mode: create | append`.

Conflict behavior:
- If create mode is requested with an already existing `pet_name`, server returns `409 PET_NAME_CONFLICT`.
- Clients should then either switch to append mode or enter a different new pet name.

`POST /v1/exemplars/upload-folder`

Purpose:
- Bulk admin registration from a folder structure.
- Expected relative paths:
  - `root/pet_name/image.ext`
  - `pet_name/image.ext`

Request (`multipart/form-data`):
- `files` (repeated): image files
- `relative_paths` (repeated): each file's relative path (same order as `files`)
- `sync_label`, `apply_to_all_instances`, `skip_on_error` (optional)

Behavior:
- Derives `pet_name` from folder name.
- Runs ingest + exemplar registration per image.
- Returns per-file success/failure summary.

`PATCH /v1/exemplars/{instance_id}`

Purpose:
- Update exemplar metadata (`pet_id`, `active`, `rank`, `note`).

`DELETE /v1/exemplars/{instance_id}`

Purpose:
- Remove exemplar status from an instance (does not delete the instance itself).

## 5.1.1) Admin image-level labeling
`POST /v1/admin/images/labels`

**Content-Type**: `application/json`

Request:
```json
{
  "date": "2026-03-15",
  "image_ids": ["img_a", "img_b"],
  "action": "ACCEPT",
  "pet_id": "pet_pomi",
  "labeled_by": "admin_dashboard",
  "confidence": 1.0,
  "source": "MANUAL",
  "select_mode": "BEST_CONFIDENCE"
}
```

Behavior:
- The dashboard can operate on `image_id` cards instead of raw `instance_id`.
- `ACCEPT`, `CLEAR`, `REJECT` are supported.
- `select_mode=BEST_CONFIDENCE` picks one representative daily instance per image.
- `select_mode=ALL` applies to all daily instances in the image.
- Seed images are excluded from the target pool.
- Label updates are mirrored to local meta sidecars.

Response:
- `action`, `pet_id`, `labeled_at`
- `items[]`: `image_id`, `selected_instance_ids[]`, `updated_count`, `skipped_reason`

## 5.2) Auto Classification (date scope)
`POST /v1/classify/auto`

**Content-Type**: `application/json`

```json
{
  "date": "2026-02-13",
  "auto_accept_threshold": 0.78,
  "candidate_threshold": 0.62,
  "search_limit": 200,
  "dry_run": false
}
```

Behavior:
- `date` is interpreted in business timezone (`settings.business_tz`, default `Asia/Seoul`).
- Target: instances on the given date that are not `assignment_status=ACCEPTED` and have no `pet_id`.
- Exemplar pool: instances explicitly registered as exemplar (`is_seed=true`, `seed_pet_id` set, `seed_active=true`) in the global pool.
- Decision:
  - `score >= auto_accept_threshold`: write `pet_id`, `assignment_status=ACCEPTED`
  - `candidate_threshold <= score < auto_accept_threshold`: write candidate only (`auto_pet_id`, `assignment_status=UNREVIEWED`)
  - below threshold: keep `UNREVIEWED`
- When `dry_run=true`, no payload/sidecar updates are written.

## 5.3) Similar Search In Current Tab
`POST /v1/classify/similar`

**Content-Type**: `application/json`

```json
{
  "date": "2026-02-13",
  "tab": "UNCLASSIFIED",
  "include_seed": false,
  "query_instance_ids": ["ins_..."],
  "merge": "RRF",
  "top_k_images": 200,
  "per_query_limit": 400
}
```

Behavior:
- `date` is interpreted in business timezone (`settings.business_tz`, default `Asia/Seoul`).
- Uses the selected query instances as exemplars.
- Candidate set is restricted to images currently visible in tab scope:
  - `ALL`
  - `UNCLASSIFIED`
  - `PET` (`pet_id` required)
- By default, seed(exemplar) images are excluded (`include_seed=false`).
- Returns tab-local image ranking by similarity score.
- Each result also includes `raw_url` and `thumb_url` for direct gallery rendering.

## 5.4) Finalize Daily Buckets
`POST /v1/buckets/finalize`

**Content-Type**: `application/json`

```json
{
  "date": "2026-02-13",
  "pet_ids": ["pet_a", "pet_b"]
}
```

Behavior:
- `date` is interpreted in business timezone (`settings.business_tz`, default `Asia/Seoul`).
- Scans accepted assignments (`assignment_status=ACCEPTED`) on that day.
- Builds per-pet daily buckets.
- Persists manifest JSON under:
  - `storage_dir/buckets/{YYYY-MM-DD}/finalize_*.json`
- Each bucket contains both:
  - `image_ids[]`
  - `images[]` with per-image export metadata: `image_id`, `file_name`, `original_filename`, `raw_path`, `raw_url`, `captured_at`
- Response/manifest includes `quality_metrics`:
  - `total_day_images`, `unclassified_images`, `unclassified_image_ratio`
  - `total_instances`, `accepted_instances`, `accepted_auto_instances`
  - `unreviewed_instances`, `rejected_instances`, `auto_accept_ratio`
- `pet_name` is also included when available from the global pet registry.

Response bucket item example:
```json
{
  "pet_id": "pet_pomi",
  "pet_name": "뽀미",
  "image_ids": ["img_a", "img_b"],
  "images": [
    {
      "image_id": "img_a",
      "file_name": "img_a.jpg",
      "original_filename": "IMG_1234.JPG",
      "raw_path": "data/reid/images/daily/img_a.jpg",
      "raw_url": "/v1/images/img_a?variant=raw",
      "captured_at": "2026-03-26T09:00:00+09:00"
    }
  ],
  "count": 2
}
```

`GET /v1/buckets/{day}`

Query:
- `manifest` (optional): explicit manifest filename. If omitted, latest manifest is returned.

## 6) Embed (single image, no DB write)
`POST /v1/embed`

**Content-Type**: `multipart/form-data`

Fields:
- `file` (required) : image

Query:
- `format` (optional): `json|f32|f16` (default from server settings)
- `profile` (optional): `verification|reid` (default: `verification`)

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
- `profile` (optional): `verification|reid` (default: `verification`)

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
- `hashes` (required): CSV list of sha256 hashes
- `facebankVersion` (optional, default latest)

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
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/images/*`
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/hash_index.json`
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/facebank_meta.json`

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
- `threshold` (optional, float)
- `sharpness` (optional, float): client-computed frame sharpness
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

Notes:
- If `timestamp` has no timezone offset, server interprets it in business timezone (`settings.business_tz`, default `Asia/Seoul`).
- If the same `id` already exists, response status becomes `duplicate` and `stored=false`.
- When `petName` is omitted, the server stores under fallback path `verification_storage_dir/trials/{YYYY-MM-DD}`.

Storage (PoC):
- `verification_storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.json`
- `verification_storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.jpg`

`GET /v1/buckets/{day}/zip`

Purpose:
- Build and return a ZIP archive from the finalized daily buckets.
- Archive layout: `{root_folder_name}/{pet_name}/{daily_images}`
- The generated ZIP is deleted from the server after the response is sent.

Query:
- `manifest` (optional): specific manifest filename to export
- `root_folder_name` (optional): override archive root folder name

Notes:
- Uses `images[].raw_path` from the manifest when available.
- Older manifests without `images[]` are backward-compatible: server resolves `image_id -> meta -> raw_path` before zipping.
- If `original_filename` is available, it is preferred as the file name inside the ZIP.



## Daily ZIP Annotation Contract

`GET /v1/daily/{day}/zip` returns a date-rooted archive that contains:
- the original daily image file
- a paired annotation file named `{image_stem}_anno.json`

The annotation JSON includes:
- `image_id`
- `img_name`
- `image_role`
- `captured_at`
- `width`
- `height`
- `instances[]`
  - `instance_id`
  - `name`
  - `pet_id`
  - `bbox`
  - `assignment_status`

Exemplar downloads remain image-only in the current implementation. Exemplar images are intended to be single-subject query/reference images.
