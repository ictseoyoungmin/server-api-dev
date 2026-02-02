# PoC GPU server image
# Run with: docker run --gpus all -p 8000:8000 dogface-api

FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

WORKDIR /app

# System deps (optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app ./app

# HuggingFace caches (mount as volume in production)
ENV HF_HOME=/models/hf
ENV TRANSFORMERS_CACHE=/models/hf
ENV TORCH_HOME=/models/torch

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
