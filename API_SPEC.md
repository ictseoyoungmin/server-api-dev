# API Spec (PoC)

Base URL (default): `http://<host>:8001` (see `run_api.sh`)

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
- `instances[]`: per detected instance: `instance_id`, `class_id`, `species`, `confidence`, `bbox` (+ optional `embedding`)

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
