# Android Client Agent Handoff (Semi-Auto Classification)

## 1) 목적
본 문서는 Android Studio 클라이언트 Agent가 서버 API를 정확히 연동하고, 훈련사 업무 흐름에 맞는 UI/UX를 구현하도록 전달하는 개발 기준서다.

대상 서버 프로젝트:
- `/workspace/PoC/dogface_fastapi_poc_qdrant`
- API Prefix: `/v1`

핵심 목표:
- 하루 촬영 이미지(약 2,000장)를 반자동 분류하고, 훈련사가 빠르게 검수/보정한 뒤 주인 전송 버킷을 확정한다.

---

## 2) 클라이언트 핵심 사용자 흐름

1. 날짜 선택
2. 갤러리 탭 진입
- `ALL`: 전체 이미지
- `UNCLASSIFIED`: 미분류 우선 검수 대상
- `PET`: 특정 반려동물 확정 이미지
3. 반자동 분류 실행 (`/classify/auto`)
4. 이미지 멀티 선택 후 유사 정렬 (`/classify/similar`)
5. 선택 이미지 수동 라벨 액션 (`/labels`: ACCEPT/REJECT/CLEAR)
6. 일자 버킷 확정 (`/buckets/finalize`) 및 확인 (`/buckets/{day}`)

---

## 3) API 연동 계약 (Client 관점)

## 3.1 갤러리 조회
`GET /v1/images`

Query:
- `date` (optional, `YYYY-MM-DD`, UTC)
- `tab` (optional: `ALL | UNCLASSIFIED | PET`)
- `pet_id` (required when `tab=PET`)
- `limit`, `offset`

UI 사용:
- 상단 탭 전환 시 query 재호출
- 무한 스크롤 시 `offset += pageSize`

## 3.2 이미지 메타 조회
`GET /v1/images/{image_id}/meta`

UI 사용:
- 상세 뷰에서 instance bbox/라벨 상태 표시
- 선택/라벨 대상 instance_id 확보

## 3.3 반자동 분류 실행
`POST /v1/classify/auto`

Request 예시:
```json
{
  "date": "2026-02-13",
  "auto_accept_threshold": 0.78,
  "candidate_threshold": 0.62,
  "search_limit": 200,
  "dry_run": false
}
```

UI 사용:
- "자동 분류" 버튼 클릭 시 실행
- 응답 `summary`를 배너/토스트로 요약 표시
- 성공 후 현재 탭 데이터 새로고침

## 3.4 탭 내부 유사 이미지 정렬
`POST /v1/classify/similar`

Request 예시:
```json
{
  "date": "2026-02-13",
  "tab": "UNCLASSIFIED",
  "query_instance_ids": ["ins_..."],
  "merge": "RRF",
  "top_k_images": 200,
  "per_query_limit": 400
}
```

응답 포인트:
- `results[].image_id`
- `results[].score`
- `results[].raw_url`
- `results[].thumb_url`

UI 사용:
- 선택한 exemplar 기준으로 현재 탭 리스트를 재정렬
- score 뱃지(optional) 표시

## 3.5 수동 라벨 액션
`POST /v1/labels`

Request 예시 (ACCEPT):
```json
{
  "labeled_by": "trainer_001",
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

액션 규칙:
- `ACCEPT`: pet_id 필수
- `REJECT`: pet_id 없이 거부
- `CLEAR`: 판정 해제(미검토)

## 3.6 버킷 확정
`POST /v1/buckets/finalize`

Request 예시:
```json
{
  "date": "2026-02-13"
}
```

응답 포인트:
- `manifest_path`
- `buckets[]` (pet_id -> image_ids)
- `quality_metrics`

## 3.7 버킷 조회
`GET /v1/buckets/{day}`

옵션:
- `manifest` query로 특정 manifest 지정 가능

---

## 4) 클라이언트 데이터 모델 제안

## 4.1 화면 모델
- `GalleryTab`: `ALL | UNCLASSIFIED | PET`
- `GalleryItem`: imageId, thumbUrl, rawUrl, capturedAt, instanceCount
- `SelectionState`: selectedImageIds, selectedInstanceIds
- `LabelAction`: ACCEPT | REJECT | CLEAR

## 4.2 상태 저장
- 날짜, 탭, 선택 pet_id, 정렬 모드(similar/normal), 선택 목록은 `ViewModel + SavedStateHandle`로 유지
- 네트워크 페이징 캐시는 탭/날짜/pet_id별 key로 분리

---

## 5) UI/UX 구현 지침

## 5.1 갤러리 화면
- 상단: 날짜 선택 + 자동분류 버튼
- 2단 라인: 탭(`ALL/UNCLASSIFIED/PET`) + Pet selector chip list
- 본문: 4x4 / 8x8 전환 가능한 grid

## 5.2 멀티 선택 UX
- Long press 진입 시 선택 모드 활성화
- 우상단 체크박스 노출
- 하단 액션바:
  - `유사 정렬`
  - `포함(ACCEPT)`
  - `제외(REJECT)`
  - `해제(CLEAR)`

## 5.3 피드백 UX
- API 호출 중: 상단 linear progress + 버튼 disabled
- 성공: 짧은 snackbar (`자동분류 완료: accepted 132`)
- 실패: 재시도 액션 제공 (`재시도`)

## 5.4 품질 지표 노출
`buckets/finalize` 후 요약 카드 표시:
- 미분류율 (`unclassified_image_ratio`)
- 자동확정률 (`auto_accept_ratio`)
- accepted/unreviewed/rejected instance 카운트

---

## 6) 오류 처리 규칙

- `400`: 사용자 입력 오류 (날짜/탭/pet_id/instance_id)
- `404`: 조회 대상 없음 (벡터 미존재, manifest 없음)
- `503`: 서버 준비 안됨 (모델/DB)

UI 공통 처리:
- 메시지 매핑 테이블 운영
- 네트워크 타임아웃/일시 오류는 exponential backoff 1~2회

---

## 7) 성능/품질 요구사항

- 이미지 그리드 스크롤 끊김 최소화 (thumbnail 우선)
- 탭 전환 시 300ms 이내 skeleton 표시
- 다중 선택 100장 이상에서도 UI 블로킹 없게 비동기 처리
- 동일 요청 중복 호출 방지(debounce/throttle)

---

## 8) Android 구현 권장 스택

- Architecture: MVVM + Clean-ish usecase
- UI: Jetpack Compose
- Networking: Retrofit + OkHttp + Kotlinx Serialization/Moshi
- Async: Coroutines + Flow
- Paging: Paging 3 (또는 커스텀 offset paging)
- Image: Coil

---

## 9) QA 체크리스트 (필수)

1. `ALL/UNCLASSIFIED/PET` 탭 필터 결과가 서버 응답과 일치
2. `TAB=PET`에서 pet_id 미지정 시 에러 처리 정상
3. 선택 이미지 기반 유사 정렬 후 순서 변경 확인
4. `ACCEPT/REJECT/CLEAR` 액션이 즉시 UI 반영
5. `finalize` 후 `get buckets` 결과 일치
6. 앱 재시작 후 날짜/탭/선택 상태 복원

---

## 10) 인수인계 시 전달물

- API 환경값: `API_BASE`, test date
- 샘플 시나리오 스크립트:
  - `example_scripts/07_classification_smoke.sh`
- 서버 API 스펙:
  - `API_SPEC.md`
- 설계 문서:
  - `SEMI_AUTO_CLASSIFICATION_DESIGN.md`

