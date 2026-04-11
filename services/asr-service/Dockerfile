# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ffmpeg for video audio extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy service source
COPY . .

# Expose port (matches ASR_PORT default)
EXPOSE 8005

ENV ASR_QUANTIZE=fp32 \
    ASR_NUM_THREADS=4 \
    ASR_PORT=8005 \
    ASR_HOST=0.0.0.0 \
    ASR_TRANSLATE=false

CMD ["python", "main.py"]
