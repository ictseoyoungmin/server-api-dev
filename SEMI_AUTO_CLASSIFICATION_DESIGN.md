# Semi-Auto Classification Design (PoC -> v1.1)

## 1. Goal
Build a semi-automatic daily photo classification flow for daycare trainers.

- Daily photos: ~2,000 images.
- One image may contain multiple pets.
- Initial auto-classification target: >= 85% precision at accepted predictions.
- Human-in-the-loop: trainer confirms includes and removes wrong assignments.

## 2. Current State (from this repo)

Existing APIs already cover the core blocks:
- `POST /v1/ingest`: detect + embed + store instance vectors.
- `POST /v1/search`: instance-vector similarity search.
- `POST /v1/labels`: write `instance_id -> pet_id` to Qdrant payload.
- `GET /v1/images`, `GET /v1/images/{id}/meta`: gallery from local sidecar JSON.

Current gaps for semi-auto workflow:
- No explicit assignment state machine (unreviewed/accepted/rejected).
- No date-tab workflow API (all / unclassified / per-pet).
- No "similar image search within current tab" endpoint.
- Label writes in Qdrant are not reflected in image sidecar metadata.

## 3. Domain Model

### 3.1 Entities
- `Pet`: registered pet identity in daycare.
- `Photo`: uploaded trainer image (`image_id`), date-bound.
- `Instance`: detected object in one photo (`instance_id`), has one embedding vector.
- `Assignment`: link from one `instance_id` to one `pet_id` with source and status.

### 3.2 Assignment State
Use per-instance state in Qdrant payload:
- `assignment_status`: `UNREVIEWED | ACCEPTED | REJECTED`
- `pet_id`: currently selected pet (nullable)
- `auto_pet_id`: auto model proposal (nullable)
- `auto_score`: similarity score for auto proposal (nullable)
- `label_source`: `AUTO | MANUAL`
- `label_confidence`: float
- `labeled_at_ts`, `labeled_by`

### 3.3 Recommended Threshold Policy
Per daycare profile (configurable):
- `auto_accept_threshold` (example: 0.78)
- `candidate_threshold` (example: 0.62)

Decision:
- score >= auto_accept_threshold: set `ACCEPTED` with `label_source=AUTO`.
- candidate_threshold <= score < auto_accept_threshold: set `UNREVIEWED` with candidate.
- score < candidate_threshold: keep `UNREVIEWED` and no candidate.

## 4. API Design

## 4.1 Keep Existing APIs (with small extension)

1) `POST /v1/labels` (extend)
- Add optional fields in assignment item:
  - `action`: `ACCEPT | REJECT | CLEAR`
  - `reason` (optional)
- Behavior:
  - `ACCEPT`: set `pet_id`, `assignment_status=ACCEPTED`.
  - `REJECT`: clear `pet_id`, set `assignment_status=REJECTED`.
  - `CLEAR`: clear decision, set `assignment_status=UNREVIEWED`.

2) `GET /v1/images` (extend query)
- New optional query params:
  - `date` (YYYY-MM-DD)
  - `tab`: `ALL | UNCLASSIFIED | PET`
  - `pet_id` (required when `tab=PET`)
- Return only images matching the tab rule (based on instance assignments).

## 4.2 New APIs

1) `POST /v1/classify/auto`
- Purpose: run automatic candidate assignment for a date scope.
- Request:
  - `daycare_id`, `date`, optional `pet_ids`, optional thresholds override.
- Response:
  - counts: scanned instances, accepted, unreviewed, unchanged.

2) `POST /v1/classify/similar`
- Purpose: "find similar images" inside currently visible tab.
- Request:
  - `daycare_id`, `date`, `tab`, `pet_id?`, `query_instance_ids[]`, `limit`.
- Behavior:
  - resolve vectors from `query_instance_ids`.
  - search within tab-constrained candidate set.
  - return reordered image list by score.

3) `POST /v1/buckets/finalize`
- Purpose: lock daily send buckets per pet.
- Request:
  - `daycare_id`, `date`, optional `pet_ids`.
- Output:
  - per-pet finalized image ids + counts.
  - persisted manifest path.

4) `GET /v1/buckets/{daycare_id}/{date}`
- Purpose: read finalized bucket manifests.

## 5. Storage and Sync Rules

## 5.1 Source of truth
- Assignment truth: Qdrant payload fields.
- Image sidecar JSON remains cache/view model.

## 5.2 Sidecar sync
When label/classification changes are written, update `data/meta/{image_id}.json` instance fields:
- `pet_id`, `assignment_status`, `label_source`, `label_confidence`, `labeled_at_ts`.

This prevents UI mismatch between `/images/*` and Qdrant state.

## 6. Backend File-Level Change Plan

## 6.1 Schemas
Add files:
- `app/schemas/classification.py`
  - auto-classify request/response
  - similar-search request/response
  - finalize request/response

Modify:
- `app/schemas/labels.py`
  - add `action`, `reason`.
- `app/schemas/images.py`
  - add tab/date filters in query model (if introduced).

## 6.2 Endpoints
Add file:
- `app/api/v1/endpoints/classification.py`
  - `/classify/auto`
  - `/classify/similar`
  - `/buckets/finalize`
  - `/buckets/{daycare_id}/{date}`

Modify:
- `app/api/v1/endpoints/labels.py`
  - state-machine-aware write logic.
- `app/api/v1/endpoints/images.py`
  - tab/date/pet filtering.
- `app/api/v1/router.py`
  - register `classification` router.

## 6.3 Vector store utilities
Modify:
- `app/vector_db/qdrant_store.py`
  - helper to scroll by filters (date/daycare/tab) for batch ops.
  - helper to bulk set payload for assignment updates.

## 7. Rollout in 3 Steps

1) Step A (minimal shippable)
- Extend `/labels` with `action` state logic.
- Extend `/images` with `date/tab/pet_id` filtering.
- Keep manual process; no new auto endpoint yet.

2) Step B (automation)
- Add `/classify/auto` using existing similarity search primitives.
- Persist `auto_pet_id`, `auto_score`, `assignment_status`.

3) Step C (trainer productivity)
- Add `/classify/similar` and bucket finalize/read APIs.
- Add metrics logging for precision and correction workload.

## 8. Success Metrics
Track daily:
- accepted-auto precision
- unreviewed ratio
- manual correction rate
- avg correction actions per 100 images
- per-pet bucket completeness before send

## 9. Immediate Implementation Recommendation
Start with Step A first. It has low risk, reuses current architecture, and unlocks the UI tabs:
- `ALL`
- `UNCLASSIFIED`
- `PET`

After Step A is merged, implement Step B in the next patch.
