# Semi-Auto Classification Design (PoC -> v2.0)

## 1. Goal
Build a semi-automatic daily photo classification flow for daycare trainers, with a clear admin-managed exemplar lifecycle.

- Daily photos: ~2,000 images.
- One image may contain multiple pets.
- Initial auto-classification target: >= 85% precision at accepted predictions.
- Human-in-the-loop: trainer confirms includes and removes wrong assignments.
- Admin-in-the-loop: exemplar quality is curated in a dedicated dashboard.

## 2. Current State (from this repo)

Core APIs:
- `POST /v1/ingest`: detect + embed + store instance vectors.
- `POST /v1/labels`: write `instance_id -> pet_id` assignments.
- `GET /v1/images`, `GET /v1/images/{id}/meta`: gallery + sidecar metadata.
- `POST /v1/classify/auto`: date-scope auto classification.
- `POST /v1/classify/similar`: tab-constrained similarity sort.
- `POST /v1/buckets/finalize`, `GET /v1/buckets/...`: daily bucket finalization.

New architecture requirement:
- Exemplar selection must be independent from daily labeling outcomes.
- Exemplar CRUD/search must be first-class for admin dashboard workflows.

## 3. Domain Model

### 3.1 Entities
- `Pet`: registered identity in daycare.
- `Photo`: uploaded trainer image (`image_id`), date-bound.
- `Instance`: detected object in one photo (`instance_id`), has one embedding vector.
- `Assignment`: per-instance daily labeling state.
- `Exemplar`: admin-curated registration sample used by auto-classifier.

### 3.2 Assignment State
Qdrant payload fields:
- `assignment_status`: `UNREVIEWED | ACCEPTED | REJECTED`
- `pet_id`: selected pet for assignment (nullable)
- `auto_pet_id`, `auto_score`
- `label_source`: `AUTO | MANUAL | PROPAGATED`
- `label_confidence`, `labeled_at_ts`, `labeled_by`

### 3.3 Exemplar State
Qdrant payload fields:
- `is_seed`: bool
- `seed_pet_id`: canonical pet identity for matching
- `seed_active`: bool
- `seed_rank`: optional ordering priority
- `seed_note`: optional admin note
- `seed_created_at_ts`, `seed_created_by`
- `seed_updated_at_ts`, `seed_updated_by`

### 3.4 Threshold Policy
Per daycare profile:
- `auto_accept_threshold` (ex: 0.78)
- `candidate_threshold` (ex: 0.62)

Decision:
- `score >= auto_accept_threshold`: `ACCEPTED` + `pet_id` write.
- `candidate_threshold <= score < auto_accept_threshold`: candidate only (`UNREVIEWED`).
- lower than candidate threshold: keep `UNREVIEWED`.

## 4. API Design

### 4.1 Exemplar Management (Admin)
- `GET /v1/exemplars`: list/search exemplars (`daycare_id`, `pet_id`, `species`, `active`, `q`, paging).
- `POST /v1/exemplars`: register one or more instance IDs as exemplars.
- `PATCH /v1/exemplars/{instance_id}`: update exemplar metadata.
- `DELETE /v1/exemplars/{instance_id}`: remove exemplar status from instance.

### 4.2 Daily Classification (Trainer)
- `POST /v1/classify/auto`
  - Target: unclassified instances on the date.
  - Exemplar source: only points where `is_seed=true`, `seed_active=true`, `seed_pet_id` exists.
- `POST /v1/classify/similar`
- `POST /v1/labels`
- `POST /v1/buckets/finalize`
- `GET /v1/buckets/{daycare_id}/{date}`

## 5. Storage and Sync Rules

### 5.1 Source of Truth
- Assignment truth: Qdrant payload (`pet_id`, `assignment_status`, ...).
- Exemplar truth: Qdrant payload (`is_seed`, `seed_*`).
- Sidecar JSON (`data/meta/*.json`): view/cache model for gallery APIs.

### 5.2 Sidecar Sync
When assignment fields change, mirror into `data/meta/{image_id}.json`:
- `pet_id`, `assignment_status`, `label_source`, `label_confidence`, `labeled_at_ts`, `labeled_by`.

Exemplar fields are intentionally not required in sidecar for trainer gallery flow.

## 6. Backend Change Plan

### 6.1 Schemas
- Add `app/schemas/exemplars.py` for exemplar CRUD/search contracts.

### 6.2 Endpoints
- Add `app/api/v1/endpoints/exemplars.py`:
  - `GET/POST /exemplars`
  - `PATCH/DELETE /exemplars/{instance_id}`
- Update `app/api/v1/router.py` to register `exemplars` router.
- Update `app/api/v1/endpoints/classification.py` to use seed-only exemplar policy.

### 6.3 Vector Store Utilities
- Extend `app/vector_db/qdrant_store.py` with payload retrieval helper by `instance_id`.

## 7. Rollout Plan

1) Exemplar domain introduction
- Add exemplar payload fields and CRUD endpoints.
- Keep existing labeling APIs stable.

2) Auto-classifier switch
- Move exemplar selection from implicit labeled pool to explicit seed pool.
- Update operations runbook (exemplar registration prerequisite).

3) Admin dashboard integration
- Build web GUI for add/update/delete/search on `/v1/exemplars`.
- Add audit/quality metrics for exemplar drift.

## 8. Success Metrics
- accepted-auto precision
- unreviewed ratio
- manual correction rate
- avg correction actions per 100 images
- per-pet bucket completeness
- exemplar freshness/coverage per pet

## 9. Implementation Recommendation
Adopt exemplar CRUD first, then enforce seed-only auto-classification in production. This keeps trainer workflows stable while enabling admin governance in parallel.
