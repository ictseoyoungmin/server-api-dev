# Client API Compatibility Matrix (Verification + Re-ID)

This document defines server-side refactoring boundaries so Android clients can remain unchanged.

## 1) Goal

- Separate server storage by domain:
  - `verification/*` for verification assets (`facebanks`, `trials`)
  - `reid/*` for re-id assets (`seed`, `daily`, `meta`, `buckets`)
- Keep existing client apps working without code changes by preserving API contracts.

## 2) Verification App (REMOTE mode)

The verification client uses only these endpoints:

1. `POST /v1/embed`
2. `GET /v1/sync-images`
3. `POST /v1/sync-images`
4. `POST /v1/trials`

### Non-breaking requirements

- Keep path, method, and required params unchanged.
- Keep response field names and meaning unchanged.
- Keep threshold/score semantics unchanged.
- Keep multipart field names unchanged (`petId`, `petName`, `images`, hashes, trial fields, etc.).
- Keep success/error HTTP status behavior consistent.

If storage layout changes internally but API contract remains same, verification app changes are **not required**.

## 3) Re-ID App

Re-ID client/admin flows rely on:

- `POST /v1/ingest`
- `GET /v1/images`
- `GET /v1/pets`
- `POST /v1/classify/auto`
- `POST /v1/classify/similar`
- `POST /v1/search`
- `POST /v1/buckets/finalize`
- `GET /v1/buckets/{daycare_id}/{day}`
- `GET/POST /v1/exemplars...` (admin)

### Non-breaking requirements

- Keep query/form/body field names unchanged (`daycare_id`, `date`, `tab`, `pet_id`, etc.).
- Preserve tab semantics:
  - daily image tabs must exclude seed images by default.
- Keep `GET /v1/pets` output model stable (`pet_id`, `pet_name`, `image_count`, `instance_count`).
- Keep `auto classify` summary keys unchanged.

## 4) Known Risk During Storage Refactor

Current `/v1/pets` behavior includes fallback from `storage_dir/pets` directory scan.
This can leak legacy pet IDs even after DB/meta reset.

### Recommended fix (server-side)

- Replace `storage_dir/pets` fallback with daycare-scoped source only:
  - primary: Qdrant points filtered by `daycare_id`
  - optional: explicit daycare-scoped registry file/table
- Remove global non-daycare fallback entries from `/v1/pets`.

## 5) Migration Rules (Safe Refactor)

1. Add new storage roots (example):
   - `data/verification/daycares/{daycare_id}/...`
   - `data/reid/daycares/{daycare_id}/...`
2. Keep API handlers returning same schema during migration.
3. Add backward reader during transition (old path read-only), then remove after data migration.
4. Keep write target only in new structure.

## 6) Contract Test Checklist

Run these after refactor:

- Verification:
  - `POST /v1/embed` returns embedding array and expected dimension.
  - `GET /v1/sync-images` returns `existingHashes` correctly.
  - `POST /v1/sync-images` uploads only missing hashes.
  - `POST /v1/trials` stores and returns expected status payload.

- Re-ID:
  - Seed upload registers exemplars and does not appear in daily tabs by default.
  - Daily ingest appears in `ALL/UNCLASSIFIED`.
  - `POST /v1/classify/auto` assigns labels as before.
  - `POST /v1/buckets/finalize` excludes seed image IDs.
  - `GET /v1/pets` returns daycare-scoped list without legacy leakage.

## 7) Change Policy

- If endpoint path/method/field names change: client update required.
- If only server internal folder layout changes: client update not required.
- For unavoidable API changes, publish `v2` endpoint and keep `v1` compatibility window.

