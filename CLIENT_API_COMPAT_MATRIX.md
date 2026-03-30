# Client API Compatibility Matrix (Verification + Re-ID)

This document records the compatibility impact of the server-side refactor after removing `daycare_id` from the re-id flow.

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
- `GET /v1/buckets/{day}`
- `GET/POST /v1/exemplars...` (admin)

### Non-breaking requirements

- Keep query/form/body field names stable after the migration (`date`, `tab`, `pet_id`, etc.).
- Preserve tab semantics:
  - daily image tabs must exclude seed images by default.
- Keep `GET /v1/pets` output model stable (`pet_id`, `pet_name`, `image_count`, `instance_count`).
- Keep `auto classify` summary keys unchanged.

## 4) Known Risk During Storage Refactor

Current `/v1/pets` behavior is expected to reflect the global pet pool backed by Qdrant payloads and the shared registry.

### Recommended fix (server-side)

- Keep `/v1/pets` driven by the global Qdrant payload set plus `data/reid/registry/pets.json`.
- Avoid reintroducing daycare-scoped fallback logic.

## 5) Migration Rules (Safe Refactor)

1. Keep verification storage unchanged.
2. Use global re-id storage roots such as `data/reid/images`, `data/reid/meta`, and `data/reid/buckets/{date}`.
3. Use `data/reid/registry/pets.json` as the shared pet registry.
4. Keep API handlers aligned with the post-migration schema and route set.

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
  - `GET /v1/pets` returns the global pet list without legacy leakage.

## 7) Change Policy

- Re-id clients must now use the updated `v1` contract without `daycare_id`.
- Verification clients remain unchanged because their API surface did not move.
- If another breaking change becomes necessary later, publish a versioned compatibility plan explicitly.

