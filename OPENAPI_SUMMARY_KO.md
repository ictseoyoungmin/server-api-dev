# API 명세서 

본 문서는 `/workspace/PoC/dogface_fastapi_poc_qdrant`의 현재 서버 코드 기준으로 작성한 명세입니다.

- 기준 라우터: `app/api/v1/router.py`
- API Prefix: `/v1`
- 기본 문서 URL(런타임): `/docs` (FastAPI Swagger UI)
- 데이터 필드/저장 구조 참조: `DATA_SCHEMA_REFERENCE.md`

## 공통 사항

- 응답 JSON 필드명은 기본적으로 `snake_case`입니다.
- 이미지 업로드는 `multipart/form-data`를 사용합니다.
- 업로드 이미지 크기 제한은 `settings.max_image_bytes` (`app/core/config.py`)를 따릅니다.
- 일부 엔드포인트는 런타임 상태에 따라 `503`을 반환할 수 있습니다. (예: 모델/벡터DB 미준비)

## 앱별 사용 범위 표기 규칙

- `Face Verification 앱`: 등록/인증/Trial 수집 앱
- `Semi-Auto Classification 앱`: 인입/분류/라벨링/버킷 확정 앱
- `공통`: 두 앱 모두 사용 가능/사용 중

분리 원칙 (현재 권장 운영):
- `facebank` 데이터(`sync-images`, `trials`)는 `Face Verification 앱` 전용으로 사용
- `Semi-Auto Classification 앱`은 `facebank`를 사용하지 않음
- `Semi-Auto Classification 앱`의 exemplar(등록 기준 데이터)는 `POST/GET/PATCH/DELETE /v1/exemplars`로 관리

### 앱별 엔드포인트 요약 (빠른 참조)

현재 코드 기준 HTTP 엔드포인트 수:
- 총 28개 (`GET /` 포함, `/admin` 정적 GUI 제외)

| Endpoint | Face Verification 앱 | Semi-Auto Classification 앱 | 비고 |
| :--- | :---: | :---: | :--- |
| `GET /` | O | O | 루트 정보 / docs 진입점 안내 |
| `GET /v1/health` | O | O | 서버 연결/상태 확인 |
| `GET /v1/health/qdrant` | O | O | Qdrant 컬렉션/instance 수/이미지 수/벡터 차원 상태 |
| `POST /v1/embed` | O | (선택) | Verification의 Remote embedding |
| `POST /v1/embed/batch` | - | - | 운영 플로우보단 도구/테스트 성격 |
| `POST /v1/ingest` | - | O | 이미지 인입 + 검출 + 임베딩 |
| `POST /v1/identify` | - | O | 단건 이미지 식별(ingest + exemplar 검색) |
| `POST /v1/search` | - | (간접/실험) | 기존 gallery 검색 API |
| `POST /v1/labels` | (선택) O | O | 인스턴스 단위 라벨링 |
| `GET /v1/exemplars` | - | O | 초기 등록 이미지(Exemplar) 조회/검색 |
| `POST /v1/exemplars` | - | O | 초기 등록 이미지(Exemplar) 등록 |
| `POST /v1/exemplars/upload` | - | O | 단일 seed 이미지 빠른 등록 |
| `POST /v1/exemplars/upload-folder` | - | O | pet 폴더 기반 seed 일괄 등록 |
| `PATCH /v1/exemplars/{instance_id}` | - | O | 초기 등록 이미지(Exemplar) 수정 |
| `DELETE /v1/exemplars/{instance_id}` | - | O | 초기 등록 이미지(Exemplar) 해제 |
| `GET /v1/images` | - | O | 갤러리 조회 |
| `GET /v1/images/{image_id}` | - | O | 이미지 바이트 조회 |
| `GET /v1/images/{image_id}/meta` | (선택) O | O | 이미지/instance 메타 조회 |
| `GET /v1/pets` | (선택) O | O | 전역 pet 목록/통계 |
| `GET /v1/sync-images` | O | - | Facebank 해시 중복 체크 |
| `POST /v1/sync-images` | O | - | Facebank 이미지 업로드 |
| `POST /v1/trials` | O | - | 인증 시도/피드백 업로드 |
| `POST /v1/classify/auto` | - | O | 자동 분류 |
| `POST /v1/classify/similar` | - | O | 탭 내 유사 정렬 |
| `POST /v1/buckets/finalize` | - | O | 일자 버킷 확정 |
| `GET /v1/buckets/{day}` | - | O | 버킷 manifest 조회 |
| `GET /v1/buckets/{day}/zip` | - | O | 버킷 ZIP 다운로드 |
| `POST /v1/admin/images/labels` | - | O | 관리자용 image_id 단위 bucket 포함/해제/제외 |

## 1. 루트 / 헬스체크

### `GET /`
서비스 기본 정보 반환

사용 앱:
- 공통 (설정/디버깅 용도)

응답 예시:
```json
{
  "name": "dogface-embedding-api",
  "docs": "/docs",
  "health": "/v1/health"
}
```

### `GET /v1/health`
서비스/임베딩 모델 상태 확인

사용 앱:
- 공통

응답 예시:
```json
{
  "status": "ok",
  "model": {
    "model_name": "miewid",
    "model_version": "miewid",
    "input_size": 440,
    "dim": 2152,
    "device": "cuda:0"
  }
}
```

비고:
- 모델 미초기화 시 `model`은 `null`일 수 있습니다.

### `GET /v1/health/qdrant`
Qdrant 상태 확인 (컬렉션/instance 수/이미지 수/벡터 차원)

사용 앱:
- 공통 (운영/디버깅)

응답 예시:
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

비고:
- `points_count`는 전체 Qdrant point 수이며, 이 서버에서는 사실상 전체 instance 수로 보면 됩니다.
- `total_images`는 `data/reid/meta/*.json` 기준 전체 이미지 수입니다.
- 일부 Qdrant 빌드에서는 `vectors_count`, `indexed_vectors_count`가 `null/0`로 보일 수 있습니다.

## 2. 임베딩 (DB 저장 없음)

### `POST /v1/embed`
단일 이미지 임베딩 생성

사용 앱:
- Face Verification 앱 (Remote embedding 모드)
- Semi-Auto Classification 앱 (일반 운영 플로우에서는 미사용, 디버그/실험용 가능)

- Content-Type: `multipart/form-data`

Query Parameters:
- `format` (optional): `json | f32 | f16` (기본값은 서버 설정 `response_format`)
- `profile` (optional): `verification | reid` (기본값 `verification`)

Form Fields:
- `file` (required, file): 입력 이미지

응답:
- `format=json`: JSON
- `format=f32|f16`: `application/octet-stream` (바이너리)

JSON 응답 예시:
```json
{
  "model_version": "miewid",
  "dim": 2152,
  "embedding": [0.0123, -0.0456]
}
```

바이너리 응답 헤더:
- `X-Embedding-Dim`
- `X-Embedding-DType` (`float32` or `float16`)
- `X-Model-Version`

오류:
- `400`: 잘못된 `format`, 잘못된 이미지
- `413`: 업로드 크기 초과
- `503`: 모델 미준비

### `POST /v1/embed/batch`
배치 이미지 임베딩 생성

사용 앱:
- 주로 운영 앱 직접 호출 대상 아님 (도구/실험/배치 확인용)

- Content-Type: `multipart/form-data`

Query Parameters:
- `format` (optional): `json | f32 | f16`
- `profile` (optional): `verification | reid` (기본값 `verification`)

Form Fields:
- `files` (required, file[], repeated): 입력 이미지 목록

JSON 응답 예시:
```json
{
  "model_version": "miewid",
  "dim": 2152,
  "items": [
    { "filename": "a.jpg", "embedding": [0.01, -0.02] },
    { "filename": "b.jpg", "embedding": [0.03, -0.04] }
  ]
}
```

바이너리 응답:
- 포맷: `dogface-batch-v1`
- 헤더: `X-Embedding-Count`, `X-Embedding-Dim`, `X-Embedding-DType`, `X-Model-Version`, `X-Batch-Format`

오류:
- `400`: 잘못된 `format`, `max_batch_size` 초과
- `413`: 업로드 크기 초과
- `503`: 모델 미준비

## 3. 인제스트 (업로드 → 검출 → 임베딩 → 벡터DB 저장)

### `POST /v1/ingest`

사용 앱:
- Semi-Auto Classification 앱

- Content-Type: `multipart/form-data`

Query Parameters:
- `include_embedding` (optional, bool, default=false): 디버그 용도로 응답에 벡터 포함

Form Fields:
- `file` (required, file)
- `trainer_id` (optional, string)
- `captured_at` (optional, string, ISO8601)
- `image_role` (optional, `DAILY | SEED`, default=`DAILY`)
- `pet_name` (optional, string): `image_role=SEED`일 때 seed 하위 폴더명으로 사용

응답 개요:
- `image`: 업로드 이미지 메타
- `instances[]`: 검출된 개체별 정보 (`instance_id`, `species`, `bbox`, 필요 시 `embedding`)

응답 예시(축약):
```json
{
  "image": {
    "image_id": "img_xxx",
      "image_role": "DAILY",
    "width": 1280,
    "height": 720,
    "storage_path": "data/images/daily/img_xxx.jpg"
  },
  "instances": [
    {
      "instance_id": "ins_xxx",
      "class_id": 16,
      "species": "DOG",
      "confidence": 0.93,
      "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.9 }
    }
  ]
}
```

오류:
- `400`: 잘못된 `captured_at`, 이미지 파싱 실패
- `413`: 업로드 크기 초과
- `503`: 모델/검출기/벡터DB 미준비

저장 경로 비고:
- DAILY: `data/images/daily/*`, `data/thumbs/daily/*`
- SEED: `data/images/seed/{pet_name}/*`, `data/thumbs/seed/{pet_name}/*`

SEED 정책:
- `image_role=SEED`는 이미지당 1개 인스턴스만 저장합니다.
- 검출이 여러 개면 `confidence` 최고 인스턴스 1개만 임베딩/저장됩니다.
- `image_role=DAILY`는 multi-instance를 유지합니다.

## 3.1 `POST /v1/identify`

단일 이미지 업로드만으로 대표 instance와 pet 후보를 반환하는 식별용 엔드포인트

사용 앱:
- Semi-Auto Classification 앱

- Content-Type: `multipart/form-data`

Form Fields:
- `file` (required, file)
- `captured_at` (optional, string, ISO8601)
- `top_k` (optional, int, default=`1`, 범위 `1..50`)

응답 개요:
- `image_id`: 인입된 이미지 ID
- `instance_id`: 대표 검출 instance ID (현재는 최고 confidence 1개 사용)
- `species`: 대표 instance 종
- `bbox`: 대표 instance bbox
- `candidates[]`: exemplar 유사도 기반 pet 후보 (`pet_id`, `pet_name`, `score`)

응답 예시:
```json
{
  "image_id": "img_xxx",
  "instance_id": "ins_xxx",
  "species": "DOG",
  "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.9 },
  "candidates": [
    {
      "pet_id": "pet_pomi",
      "pet_name": "뽀미",
      "score": 0.91
    }
  ]
}
```

동작 비고:
- 내부적으로 `ingest` 후, active exemplar(`is_seed=true`, `seed_active=true`)를 cosine 유사도 기반으로 검색합니다.
- `captured_at` 미전송 시 서버 수신 시각 기준으로 ingest에 전달합니다.
- 클라이언트가 별도 `date`를 전달할 필요는 없습니다.
- 검출 instance가 여러 개면 현재는 최고 confidence instance 1개만 후보 검색에 사용합니다.

## 4. 검색 (갤러리 정렬)

### `POST /v1/search`
벡터 유사도 기반 이미지 검색 (instance-level 검색 후 image-level 집계)

사용 앱:
- 기본 Semi-Auto 분류 UI는 주로 `/v1/classify/similar` 사용
- `Face Verification 앱`에서는 일반적으로 미사용
- 실험/관리 툴에서 재사용 가능

- Content-Type: `application/json`

요청 바디:
```json
{
  "query": {
    "instance_ids": ["ins_..."],
    "merge": "RRF"
  },
  "filters": {
    "species": "DOG",
    "captured_from": "2026-02-01T00:00:00Z",
    "captured_to": "2026-02-01T23:59:59Z"
  },
  "top_k_images": 200,
  "per_query_limit": 400
}
```

비고:
- `filters.captured_from` / `filters.captured_to`에 타임존이 없으면, 서버는 비즈니스 타임존(`settings.business_tz`, 기본 `Asia/Seoul`)으로 해석합니다.

응답 예시:
```json
{
  "query_debug": {
    "used_vectors": 1,
    "merge": "MAX",
    "per_query_limit": 400,
    "top_k_images": 200
  },
  "results": [
    {
      "image_id": "img_...",
      "score": 0.1234,
      "best_match": {
        "instance_id": "ins_...",
        "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.9 },
        "score": 0.81
      }
    }
  ]
}
```

오류:
- `400`: `query.instance_ids` 누락/비정상
- `404`: 조회용 `instance_id` 벡터를 DB에서 찾지 못함
- `503`: 벡터DB 미준비

## 5. 라벨링 (instance_id → pet_id)

### `POST /v1/labels`

사용 앱:
- Semi-Auto Classification 앱 (핵심)
- Face Verification 앱 (선택: 새 pet/bucket 서버 반영 시 라벨 동기화 용도)

- Content-Type: `application/json`

요청 바디 예시:
```json
{
  "labeled_by": "tester01",
  "assignments": [
    {
      "instance_id": "ins_...",
      "pet_id": "pet_aaa",
      "action": "ACCEPT",
      "source": "MANUAL",
      "confidence": 1.0
    }
  ]
}
```

응답 예시:
```json
{
  "labeled_at": "2026-02-25T12:34:56.000000Z",
  "items": [
    {
      "instance_id": "ins_...",
      "pet_id": "pet_aaa",
      "assignment_status": "ACCEPTED",
      "updated": true
    }
  ]
}
```

비고:
- `action`: `ACCEPT | REJECT | CLEAR`
- `source`: `MANUAL | AUTO | PROPAGATED`

## 6. 이미지/메타 조회

### `GET /v1/images`
갤러리 이미지 목록 조회

사용 앱:
- Semi-Auto Classification 앱 (핵심)

Query Parameters:
- `date` (optional, string): `YYYY-MM-DD` (비즈니스 타임존 기준, 기본 `Asia/Seoul`)
- `tab` (optional): `ALL | UNCLASSIFIED | PET` (default `ALL`)
- `pet_id` (optional): `tab=PET`일 때 사용
- `include_seed` (optional, bool, default `false`)
- `limit` (optional, int, default=200)
- `offset` (optional, int, default=0)

응답 예시(축약):
```json
{
  "count": 2,
  "items": [
    {
      "image_id": "img_...",
          "image_role": "DAILY",
      "raw_url": "/v1/images/img_xxx?variant=raw",
      "thumb_url": "/v1/images/img_xxx?variant=thumb",
      "instance_count": 3,
      "pet_ids": ["pet_pomi"]
    }
  ]
}
```

### `GET /v1/images/{image_id}`
원본/썸네일 이미지 바이너리 제공

사용 앱:
- Semi-Auto Classification 앱

Query Parameters:
- `variant` (optional, string): `raw | thumb` (default=`raw`)

응답:
- 이미지 파일 바이너리 (`image/jpeg`, `image/png` 등)

오류:
- `400`: 잘못된 `variant`
- `404`: 메타/이미지 파일 없음

### `GET /v1/images/{image_id}/meta`
이미지 메타 + 검출 인스턴스 메타 조회

사용 앱:
- Semi-Auto Classification 앱 (핵심: 인스턴스 선택/라벨링)
- Face Verification 앱 (선택: 서버 인스턴스 라벨 동기화 시)

응답 예시(축약):
```json
{
  "image": {
    "image_id": "img_...",
      "width": 1280,
    "height": 720,
    "raw_url": "/v1/images/img_xxx?variant=raw",
    "thumb_url": "/v1/images/img_xxx?variant=thumb"
  },
  "instances": [
    {
      "instance_id": "ins_...",
      "class_id": 16,
      "species": "DOG",
      "confidence": 0.91,
      "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.9 },
      "pet_id": null
    }
  ]
}
```

## 7. 반려동물 목록 조회

### `GET /v1/pets`
등록/라벨된 반려동물 목록 조회 (전역 기준)

사용 앱:
- Semi-Auto Classification 앱 (PET 탭/선택 UI)
- Face Verification 앱 (선택: 서버 기준 pet 목록 동기화 UI)

Query Parameters:

응답 예시:
```json
{
  "count": 2,
  "items": [
    {
      "pet_id": "pet_aaa",
      "pet_name": "anna",
      "image_count": 12,
      "instance_count": 30
    }
  ]
}
```

비고:
- `/v1/pets`는 Qdrant payload를 직접 조회해 전역 `pet_id`와 `seed_pet_id`를 집계합니다.
- `pet_name`은 `reid_storage_dir/registry/pets.json` 전역 매핑을 우선 사용합니다.
- Classification 앱에서는 PET 탭/라벨링 대상 선택의 기준 목록으로 사용합니다.
- Verification 앱에서 사용할 경우, 서버 기준 pet 목록 동기화 UI 용도로만 사용하는 것을 권장합니다.

## 8. 초기 등록 이미지(Exemplar) 관리

### `GET /v1/exemplars`
관리자용 초기 등록 이미지 목록 조회/검색

사용 앱:
- Semi-Auto Classification 관리자 Dashboard (핵심)

Query Parameters:
- `pet_id` (optional, string)
- `species` (optional, `DOG | CAT`)
- `active` (optional, bool, default `true`)
- `q` (optional, string): `instance_id`, `image_id`, `pet_id`, `note` 부분 검색
- `limit` / `offset` (optional)

### `POST /v1/exemplars`
인스턴스를 초기 등록 이미지로 지정 (다건 등록 지원)

핵심 동작:
- `is_seed=true`, `seed_pet_id`, `seed_active` 등 exemplar 필드를 설정
- 옵션으로 `pet_id`, `assignment_status=ACCEPTED` 라벨 동기화 가능

### `POST /v1/exemplars/upload`
빠른 등록 API (단일 seed 이미지 등록)

요청 모드:
- `pet_id` 전송: 기존 pet에 exemplar 추가 (`append`)
- `pet_name` 전송: 새 pet 생성 후 exemplar 등록 (`create`)

핵심 동작:
- 내부적으로 `ingest` 수행 후 exemplar 등록까지 한 번에 처리
- 기본값으로 최고 confidence 인스턴스 1개를 등록
- `apply_to_all_instances=true` 시 검출된 모든 인스턴스를 등록

비고:
- `pet_id`와 `pet_name`은 동시에 보내지 않습니다.
- 이미 존재하는 이름으로 `create`를 시도하면 `409 PET_NAME_CONFLICT`를 반환합니다.
- 성공 응답에는 `mode=create|append`가 포함됩니다.

### `POST /v1/exemplars/upload-folder`
폴더 일괄 등록 API (폴더명 = pet_name)

요청 방식:
- `multipart/form-data`
- `files`(반복), `relative_paths`(반복, files와 동일 순서)

경로 규칙:
- `루트/pet_name/파일`
- 또는 `pet_name/파일`

동작:
- 각 파일마다 `ingest` 수행 후 exemplar 등록
- 파일별 성공/실패 결과를 요약 응답으로 반환

### `PATCH /v1/exemplars/{instance_id}`
초기 등록 이미지 속성 수정 (`pet_id`, `active`, `rank`, `note`)

### `DELETE /v1/exemplars/{instance_id}`
초기 등록 이미지 지정 해제 (`is_seed=false`)

비고:
- 반자동 자동분류(`/v1/classify/auto`)는 이 Exemplar 풀만 참조합니다.
- Facebank(`sync-images`)와는 별도 자원입니다.

### `POST /v1/admin/images/labels`
관리자 대시보드용 image-level 라벨링 API

사용 앱:
- Semi-Auto Classification 관리자 Dashboard

비고:
- `instance_id` 대신 `image_id` 배열을 받아 대표 instance를 서버가 선택합니다.
- `action=ACCEPT | CLEAR | REJECT`를 지원합니다.
- 현재 관리자 Dashboard UI는 주로 `ACCEPT`, `CLEAR`를 노출합니다. (`REJECT`는 백엔드 지원만 유지)
- `select_mode=BEST_CONFIDENCE | ALL` 를 지원합니다.
- seed 이미지는 대상에서 제외하고, Qdrant payload와 local meta sidecar를 함께 갱신합니다.

요청 바디 예시:
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

응답 예시:
```json
{
  "action": "ACCEPT",
  "pet_id": "pet_pomi",
  "labeled_at": "2026-03-15T10:00:00Z",
  "items": [
    {
      "image_id": "img_a",
      "selected_instance_ids": ["ins_..."],
      "updated_count": 1,
      "skipped_reason": null
    }
  ]
}
```

## 9. Facebank 이미지 동기화 (해시 기반 중복 제거)

### `GET /v1/sync-images`
클라이언트가 가진 facebank 이미지 해시 중 서버에 이미 있는 항목 조회

사용 앱:
- Face Verification 앱 (핵심)

비고:
- `facebank` 저장/동기화 전용 API입니다.
- Semi-Auto Classification 앱의 등록/분류 exemplar 파이프라인에는 사용하지 않습니다.

Query Parameters:
- `petId` (required, string)
- `petName` (optional, string): 서버 폴더 경로 그룹핑에 사용
- `facebankId` (required, string)
- `facebankVersion` (optional, int): 생략 시 최신 버전 탐색
- `hashes` (required, string): SHA-256 CSV 목록

응답 예시:
```json
{
  "existing_hashes": [
    "8653a0...",
    "5bfc8d..."
  ]
}
```

비고:
- 서버 응답은 `existing_hashes` (`snake_case`) 입니다.
- 서버는 일부 레거시 경로(`data/pets/{petId}/{facebankId}/vN`)도 조회 호환합니다.

### `POST /v1/sync-images`
서버에 없는 facebank 이미지 업로드 및 메타 저장

사용 앱:
- Face Verification 앱 (핵심)

비고:
- 서버에 facebank 원본/해시/메타를 저장하지만, 이 데이터만으로는 Classification용 exemplar(`is_seed`)가 생성되지 않습니다.
- Semi-Auto Classification 앱의 초기 exemplar는 `/v1/exemplars` API로 별도 관리합니다.

- Content-Type: `multipart/form-data`

Form Fields:
- `petId` (required, string)
- `petName` (required, string)
- `facebankId` (required, string)
- `facebankVersion` (required, int)
- `images` (required, file[], repeated)
- `hashes` (required, string[], repeated)
- `modelVersion` (optional, string)
- `embeddingDim` (optional, int)
- `threshold` (optional, float)
- `deviceId` (optional, string)
- `createdAt` (optional, string, ISO8601)

응답 예시:
```json
{
  "pet_id": "747094aa-cece-42f5-88d2-4115ae6e6500",
  "facebank_id": "12efd248-7473-4691-b21f-e960ed428125",
  "facebank_version": 1,
  "received": 5,
  "skipped": 0,
  "stored": 5,
  "existing_hashes": [],
  "model_version": null,
  "embedding_dim": null,
  "threshold": null,
  "device_id": null
}
```

오류:
- `400`: `images`와 `hashes` 개수 불일치
- `413`: 업로드 크기 초과
- `500`: 해시 인덱스 파일 파싱 실패

저장 구조 (현재 코드 기준):
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/images/*`
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/hash_index.json`
- `verification_storage_dir/pets/{petId}/{petName}/facebanks/{facebankId}/v{facebankVersion}/facebank_meta.json`

## 9. 인증 시도(Trial) 업로드

### `POST /v1/trials`
인증 시도 결과 + 사용자 피드백 + 캡처 이미지를 저장

사용 앱:
- Face Verification 앱 (핵심)

비고:
- Verification 성능 데이터 수집용 API이며, Semi-Auto Classification 플로우와는 독립입니다.

- Content-Type: `multipart/form-data`

Form Fields:
- `id` (required, string): trial UUID (idempotency key)
- `petId` (required, string)
- `petName` (optional, string): 서버 폴더 경로 그룹핑에 사용
- `facebankId` (required, string)
- `facebankVersion` (required, int)
- `score` (required, float)
- `threshold` (optional, float)
- `isSuccess` (required, bool)
- `userFeedback` (required, bool)
- `timestamp` (optional, string): ISO8601 (`Z` 허용)
- `pose` (optional, string)
- `trialImage` (required, file)

응답 예시 (신규 저장):
```json
{
  "trial_id": "01be0cd7-226e-4b96-8aac-7fc93e91371f",
  "status": "stored",
  "stored": true,
  "storage_path": "data/verification/pets/{petId}/{petName}/trials/2026-02-06/01be0cd7-....json",
  "outcome": "TP"
}
```

응답 예시 (중복 trial_id):
```json
{
  "trial_id": "01be0cd7-226e-4b96-8aac-7fc93e91371f",
  "status": "duplicate",
  "stored": false,
  "storage_path": "data/verification/pets/{petId}/{petName}/trials/2026-02-06/01be0cd7-....json",
  "outcome": null
}
```

서버 내부 판정 라벨 (`outcome`) 계산식:
- `TP`: `isSuccess=true` and `userFeedback=true`
- `FP`: `isSuccess=true` and `userFeedback=false`
- `FN`: `isSuccess=false` and `userFeedback=true`
- `TN`: `isSuccess=false` and `userFeedback=false`

오류:
- `400`: `timestamp` 형식 오류 (현재 서버는 ISO8601 문자열 기대)
- `413`: 업로드 크기 초과

비고:
- `timestamp`에 타임존 정보가 없으면 서버는 비즈니스 타임존(`settings.business_tz`, 기본 `Asia/Seoul`) 기준으로 해석합니다.

저장 구조 (현재 코드 기준):
- `verification_storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.json`
- `verification_storage_dir/pets/{petId}/{petName}/trials/{YYYY-MM-DD}/{trial_id}.{jpg|png|webp}`
- (`petName` 미전송 시 fallback 경로 `verification_storage_dir/trials/{YYYY-MM-DD}` 사용)

## 10. 분류 보조/버킷 확정 (Semi-auto Classification)

### `POST /v1/classify/auto`
미분류 인스턴스에 대해 자동 분류를 수행하고 라벨 상태를 갱신

사용 앱:
- Semi-Auto Classification 앱 (핵심)

비고:
- 동작 전제: Qdrant에 `is_seed=true` 및 `seed_pet_id`가 설정된 exemplar 인스턴스가 존재해야 합니다.
- 비교 풀은 같은 daycare(+optional species)의 exemplar(초기 등록 이미지) 인스턴스입니다.
- facebank 동기화 데이터는 직접 사용하지 않습니다.

- Content-Type: `application/json`
- Form Fields: 없음 (JSON Body 사용)

요청 주요 필드:
- `date` (date, 비즈니스 타임존 기준; `settings.business_tz`, 기본 `Asia/Seoul`)
- `species` (optional: `DOG | CAT`)
- `auto_accept_threshold` (float, default 0.78)
- `candidate_threshold` (float, default 0.62)
- `search_limit` (int, default 200)
- `labeled_by` (optional)
- `dry_run` (bool, default false)

요청 바디 예시:
```json
{
  "date": "2026-02-13",
  "species": "DOG",
  "auto_accept_threshold": 0.78,
  "candidate_threshold": 0.62,
  "search_limit": 200,
  "labeled_by": "trainer_001",
  "dry_run": false
}
```

응답 주요 필드:
- `requested_at`
- `date`, `dry_run`
- `summary` (`scanned_instances`, `accepted`, `unreviewed_candidate`, ...)
- `items[]` (`instance_id`, `image_id`, `score`, `selected_pet_id`, `assignment_status`, `updated`)

응답 예시(축약):
```json
{
  "requested_at": "2026-02-25T10:10:10.100000Z",
  "date": "2026-02-13",
  "dry_run": false,
  "summary": {
    "scanned_instances": 320,
    "accepted": 180,
    "unreviewed_candidate": 90,
    "unreviewed_no_candidate": 50,
    "unchanged": 12
  },
  "items": [
    {
      "instance_id": "ins_aaa",
      "image_id": "img_111",
      "species": "DOG",
      "score": 0.83,
      "selected_pet_id": "pet_pomi",
      "assignment_status": "ACCEPTED",
      "updated": true
    }
  ]
}
```

### `POST /v1/classify/similar`
분류 UI용 유사 이미지 검색 (일자/탭/펫 기준)

사용 앱:
- Semi-Auto Classification 앱 (핵심)

- Content-Type: `application/json`
- Form Fields: 없음 (JSON Body 사용)

요청 주요 필드:
- `date` (date, 비즈니스 타임존 기준; `settings.business_tz`, 기본 `Asia/Seoul`)
- `tab` (`ALL | UNCLASSIFIED | PET`)
- `pet_id` (optional, `tab=PET`일 때 주로 사용)
- `query_instance_ids` (string[], min 1)
- `merge` (`MAX | RRF`, default `MAX`)
- `top_k_images` (int)
- `per_query_limit` (int)

요청 바디 예시:
```json
{
  "date": "2026-02-13",
  "tab": "UNCLASSIFIED",
  "pet_id": null,
  "query_instance_ids": ["ins_aaa", "ins_bbb"],
  "merge": "MAX",
  "top_k_images": 200,
  "per_query_limit": 400
}
```

응답 주요 필드:
- `requested_at`, `date`, `tab`, `pet_id`
- `query_debug`
- `results[]` (`image_id`, `score`, `best_match_instance_id`, `best_match_score`, `raw_url`, `thumb_url`)

응답 예시(축약):
```json
{
  "requested_at": "2026-02-25T10:20:20.200000Z",
  "date": "2026-02-13",
  "tab": "UNCLASSIFIED",
  "pet_id": null,
  "query_debug": {
    "used_vectors": 2,
    "merge": "MAX",
    "per_query_limit": 400,
    "top_k_images": 200,
    "allowed_images": 128
  },
  "results": [
    {
      "image_id": "img_999",
      "score": 0.0412,
      "best_match_instance_id": "ins_xxx",
      "best_match_score": 0.8123,
      "raw_url": "/v1/images/img_999?variant=raw",
      "thumb_url": "/v1/images/img_999?variant=thumb"
    }
  ]
}
```

### `POST /v1/buckets/finalize`
하루치 라벨 결과를 바탕으로 pet별 이미지 버킷을 확정하고 manifest 저장

사용 앱:
- Semi-Auto Classification 앱 (핵심)

- Content-Type: `application/json`

요청 바디:
```json
{
  "date": "2026-02-25",
  "pet_ids": ["pet_id_1", "pet_id_2"]
}
```

응답 예시 (중요: `buckets`는 배열):
```json
{
  "finalized_at": "2026-02-25T12:34:56.789000Z",
  "date": "2026-02-25",
  "bucket_count": 2,
  "total_images": 3,
  "quality_metrics": {
    "total_day_images": 20,
    "unclassified_images": 5,
    "unclassified_image_ratio": 0.25,
    "total_instances": 42,
    "accepted_instances": 30,
    "accepted_auto_instances": 18,
    "unreviewed_instances": 8,
    "rejected_instances": 4,
    "auto_accept_ratio": 0.4285714286
  },
  "manifest_path": "data/buckets/dc_001/2026-02-25/finalize_20260225T123456Z.json",
  "buckets": [
    {
      "pet_id": "pet_id_1",
      "pet_name": "뽀미",
      "image_ids": ["image_id_1", "image_id_2"],
      "images": [
        {
          "image_id": "image_id_1",
          "file_name": "img_abc.jpg",
          "original_filename": "IMG_1234.JPG",
          "raw_path": "data/reid/images/daily/img_abc.jpg",
          "raw_url": "/v1/images/image_id_1?variant=raw",
          "captured_at": "2026-02-25T09:10:11+09:00"
        }
      ],
      "count": 2
    }
  ]
}
```

비고:
- `buckets`는 `Map<String, List<String>>`가 아니라 `List[FinalizeBucketItem]` 입니다.
- 각 bucket은 `image_ids[]`와 `images[]`를 함께 가질 수 있습니다.
- `images[]`는 ZIP export용 메타(`raw_path`, `original_filename` 등)를 포함합니다.
- `manifest_path`, `quality_metrics`는 `snake_case` 필드명입니다.

### `GET /v1/buckets/{day}`
저장된 일자 버킷 manifest 조회

사용 앱:
- Semi-Auto Classification 앱 (핵심)

Path Parameters:
- `day` (date, `YYYY-MM-DD`)

Query Parameters:
- `manifest` (optional, string): 특정 manifest 파일명 지정

응답 구조:
- `FinalizeBucketsResponse`와 유사 (`manifest_path`, `quality_metrics`, `buckets[]`)
- 기존 manifest라도 서버가 가능하면 `images[]`를 복원해 함께 내려줍니다.

응답 예시(축약):
```json
{
  "date": "2026-02-13",
  "manifest_path": "data/buckets/2026-02-13/finalize_20260225T101133Z.json",
  "finalized_at": "2026-02-25T10:11:33.000000Z",
  "bucket_count": 3,
  "total_images": 87,
  "quality_metrics": {
    "total_day_images": 120,
    "unclassified_images": 33,
    "unclassified_image_ratio": 0.275,
    "total_instances": 210,
    "accepted_instances": 150,
    "accepted_auto_instances": 96,
    "unreviewed_instances": 48,
    "rejected_instances": 12,
    "auto_accept_ratio": 0.4571
  },
  "buckets": [
    {
      "pet_id": "pet_pomi",
      "pet_name": "뽀미",
      "image_ids": ["img_1", "img_2"],
      "images": [
        {
          "image_id": "img_1",
          "file_name": "img_1.jpg",
          "original_filename": "IMG_0001.JPG",
          "raw_path": "data/reid/images/daily/img_1.jpg",
          "raw_url": "/v1/images/img_1?variant=raw",
          "captured_at": "2026-02-13T08:30:00+09:00"
        }
      ],
      "count": 2
    }
  ]
}
```

### `GET /v1/buckets/{day}/zip`
저장된 버킷 manifest를 기준으로 ZIP 파일 다운로드

사용 앱:
- Semi-Auto Classification 앱 (핵심)
- for_admin 대시보드의 ZIP 다운로드 버튼과 연결

Path Parameters:
- `day` (date, `YYYY-MM-DD`)

Query Parameters:
- `manifest` (optional, string): 특정 manifest 파일명 지정
- `root_folder_name` (optional, string): ZIP 루트 폴더명 지정

동작 비고:
- ZIP 내부 구조는 기본적으로 `{root_folder_name}/{pet_name}/{daily_images}` 입니다.
- manifest에 `images[]`가 있으면 `raw_path`를 그대로 사용합니다.
- 응답 전송이 끝나면 생성된 ZIP 임시 파일은 서버에서 삭제됩니다.
- 예전 manifest처럼 `image_ids[]`만 있어도 서버가 meta를 읽어 `raw_path`를 복원해 압축합니다.
- `original_filename`이 있으면 ZIP 내부 파일명으로 우선 사용합니다.

응답:
- `application/zip`

## 에러 코드 요약 (빈번)

- `400 Bad Request`
  - 파라미터/바디 검증 실패(비즈니스 로직 레벨)
  - 잘못된 timestamp/format 등
- `404 Not Found`
  - 이미지/메타 없음
  - 검색용 query 벡터 미존재
- `413 Payload Too Large`
  - 업로드 이미지 크기 제한 초과
- `422 Unprocessable Entity`
  - FastAPI 레벨 필드 누락/타입 불일치 (예: 필수 Query/Form 누락)
- `500 Internal Server Error`
  - 파일 파싱 오류 등 서버 내부 예외
- `503 Service Unavailable`
  - 모델/검출기/벡터DB 미준비

## 참고 파일

- 라우터: `app/api/v1/router.py`
- 엔드포인트: `app/api/v1/endpoints/`
- 스키마: `app/schemas/`
- 설정: `app/core/config.py`


## Daily ZIP Annotation Contract

`GET /v1/daily/{day}/zip`는 날짜 폴더 아래에 다음을 함께 제공합니다.
- 원본 daily 이미지 파일
- 같은 stem을 사용하는 `{image_stem}_anno.json`

`_anno.json`에는 다음이 포함됩니다.
- `image_id`
- `img_name`
- `image_role`
- `captured_at`
- `width` / `height`
- `instances[]`
  - `instance_id`
  - `name`
  - `pet_id`
  - `bbox`
  - `assignment_status`

Exemplar 다운로드는 현재 이미지 파일만 포함합니다. Exemplar 이미지는 query/reference 용도이므로 단일 개체 이미지 사용을 권장합니다.
