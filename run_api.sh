source /workspace/PoC/dogface_fastapi_poc_qdrant/.envqd/bin/activate

set -a
source /workspace/PoC/dogface_fastapi_poc_qdrant/.env
set +a

uvicorn app.main:app --host 0.0.0.0 --port 8001
