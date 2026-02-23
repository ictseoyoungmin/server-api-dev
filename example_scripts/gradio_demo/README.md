# Gradio Demo

Semi-auto classification 흐름을 웹에서 최소 기능으로 검증하는 데모입니다.

## 실행

```bash
cd /workspace/PoC/dogface_fastapi_poc_qdrant
python3 -m pip install gradio requests
bash example_scripts/gradio_demo/run_gradio_demo.sh
```

기본 접속:
- `http://localhost:7860`

환경변수:
- `API_BASE` (default: `http://localhost:8001`)
- `DAYCARE_ID` (default: `dc_001`)
- `GRADIO_PORT` (default: `7860`)
- `PYTHON_BIN` (default: `python3`)

## 포함 기능

- `GET /v1/pets`: PET 탭 선택용 `pet_id/pet_name` 목록 조회
- `GET /v1/images`: 날짜/탭(`ALL|UNCLASSIFIED|PET`) 기준 갤러리 조회
- `POST /v1/classify/auto`: 반자동 분류 실행
- `POST /v1/classify/similar`: 선택 이미지 기준 탭 내부 유사 정렬
- `POST /v1/labels`: ACCEPT/REJECT/CLEAR 라벨 액션
- `POST /v1/buckets/finalize`: 일자 버킷 확정
- `GET /v1/buckets/{daycare_id}/{day}`: 버킷 조회

## 사용 순서 권장

1. `Load Pets` (PET 목록 로드, `pet_id` 드롭다운 채움)
2. `Load Gallery`
3. 이미지 선택
4. `Sort Similar In Tab`
5. `Apply Label Action`
6. `Run Auto Classify` (옵션)
7. `Finalize Buckets` -> `Get Buckets`
