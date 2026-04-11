"""
services/asr-service/main.py

Paraline ASR Service — Gipformer Vietnamese Speech Recognition

Endpoints:
    POST /transcribe/file  — Upload a WAV/FLAC audio file → transcript
    POST /transcribe/video — Upload a video file → extract audio → transcript
    GET  /health           — Service health check

Environment variables:
    ASR_QUANTIZE      fp32 | int8       (default: fp32)
    ASR_NUM_THREADS   int               (default: 4)
    ASR_HOST          bind host         (default: 0.0.0.0)
    ASR_PORT          bind port         (default: 8005)
    ASR_TRANSLATE     true | false      (default: false)
"""

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf  # type: ignore[import-untyped]
import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import (  # type: ignore[import-not-found]
    check_ffmpeg,
    get_recognizer,
    load_audio_from_video,
    transcribe_samples,
    translate_all,
    translator_available,
)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger("paraline.asr")

QUANTIZE = os.getenv("ASR_QUANTIZE", "fp32")
NUM_THREADS = int(os.getenv("ASR_NUM_THREADS", "4"))
HOST = os.getenv("ASR_HOST", "0.0.0.0")
PORT = int(os.getenv("ASR_PORT", "8005"))
AUTO_TRANSLATE = os.getenv("ASR_TRANSLATE", "false").lower() == "true"

SUPPORTED_AUDIO_EXTS = {".wav", ".flac", ".ogg", ".mp3", ".m4a"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}

# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Paraline ASR Service",
    description="Vietnamese speech recognition powered by Gipformer (sherpa-onnx).",
    version="1.0.0",
)

# CORS — cho phép cabin_ui (file://  hoặc localhost) gọi trực tiếp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Pre-load the Gipformer model at startup to avoid cold-start latency."""
    logger.info("🚀 Initialising Gipformer ASR (quantize=%s, threads=%d) ...", QUANTIZE, NUM_THREADS)
    get_recognizer(quantize=QUANTIZE, num_threads=NUM_THREADS)
    logger.info("✅ ASR service ready on %s:%d", HOST, PORT)


# ──────────────────────────────────────────────────────────────────────────────
# Request model cho JSON transcribe endpoint
# ──────────────────────────────────────────────────────────────────────────────

class TranscribeJsonReq(BaseModel):
    audio_b64: str              # float32 PCM dạng base64 (output từ InboundAudioManager)
    sample_rate: int = 16000


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_response(
    text: str,
    elapsed_s: float,
    audio_duration_s: float,
    translate: bool,
) -> dict:
    response: dict = {
        "transcript": text,
        "audio_duration_s": round(audio_duration_s, 3),
        "latency_ms": round(elapsed_s * 1000, 1),
        "rtf": round(elapsed_s / audio_duration_s, 4) if audio_duration_s > 0 else None,
    }
    if translate and text:
        if translator_available():
            response["translations"] = translate_all(text)
        else:
            response["translations"] = {
                "en": "[deep-translator not installed]",
                "ja": "[deep-translator not installed]",
            }
    return response
@app.post("/transcribe", summary="Transcribe audio from base64 float32 PCM (JSON, used by Cabin UI)")
async def transcribe_json(req: TranscribeJsonReq):
    """Nhận audio dạng float32 PCM được mã hoá Base64 (InboundAudioManager output).

    Request JSON:
        { "audio_b64": "<base64 float32 bytes>", "sample_rate": 16000 }

    Response:
        { "transcript": "...", "latency_ms": 312.5 }
    """
    try:
        raw_bytes = base64.b64decode(req.audio_b64)
        samples = np.frombuffer(raw_bytes, dtype=np.float32)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot decode audio_b64: {exc}") from exc

    if len(samples) == 0:
        return {"transcript": "", "latency_ms": 0.0}

    sr = req.sample_rate
    audio_duration = len(samples) / sr
    recognizer = get_recognizer(quantize=QUANTIZE, num_threads=NUM_THREADS)

    t0 = time.perf_counter()
    text = transcribe_samples(recognizer, samples, sample_rate=sr)
    elapsed = time.perf_counter() - t0

    logger.info(
        "transcribe/json  duration=%.1fs  latency=%.0fms  rtf=%.3f  text=%r",
        audio_duration, elapsed * 1000,
        elapsed / audio_duration if audio_duration > 0 else 0, text[:80],
    )

    return {
        "transcript": text,
        "audio_duration_s": round(audio_duration, 3),
        "latency_ms": round(elapsed * 1000, 1),
        "rtf": round(elapsed / audio_duration, 4) if audio_duration > 0 else None,
    }



@app.post("/transcribe/file", summary="Transcribe an audio file (WAV, FLAC, OGG, MP3, M4A)")
async def transcribe_file(
    file: UploadFile = File(..., description="Audio file to transcribe"),
    translate: bool = Query(False, description="Also translate transcript to EN and JA"),
):
    """Upload an audio file and receive a Vietnamese transcript.

    - Supported formats: WAV, FLAC, OGG, MP3, M4A
    - The recogniser is pre-loaded at startup; subsequent requests are fast.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_AUDIO_EXTS))}",
        )

    raw = await file.read()
    try:
        samples, sr = sf.read(io.BytesIO(raw), dtype="float32")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot read audio file: {exc}") from exc

    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    audio_duration = len(samples) / sr
    recognizer = get_recognizer(quantize=QUANTIZE, num_threads=NUM_THREADS)

    t0 = time.perf_counter()
    text = transcribe_samples(recognizer, samples, sample_rate=sr)
    elapsed = time.perf_counter() - t0

    logger.info(
        "transcribe/file  file=%s  duration=%.1fs  latency=%.0fms  rtf=%.3f  text=%r",
        file.filename, audio_duration, elapsed * 1000,
        elapsed / audio_duration if audio_duration > 0 else 0, text[:80],
    )

    return _build_response(text, elapsed, audio_duration, translate or AUTO_TRANSLATE)


@app.post("/transcribe/video", summary="Extract audio from a video file and transcribe it")
async def transcribe_video(
    file: UploadFile = File(..., description="Video file to transcribe"),
    translate: bool = Query(False, description="Also translate transcript to EN and JA"),
):
    """Upload a video file; the service extracts audio with ffmpeg then transcribes.

    - Supported formats: MP4, MKV, AVI, MOV, WEBM, FLV, WMV, M4V, TS
    - Requires `ffmpeg` to be installed and available in PATH.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_VIDEO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTS))}",
        )

    # Persist upload to a temp file (ffmpeg needs a real path)
    raw = await file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        ffmpeg_cmd = check_ffmpeg()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        t_extract = time.perf_counter()
        samples = load_audio_from_video(tmp_path, ffmpeg_cmd=ffmpeg_cmd)
        extract_elapsed = time.perf_counter() - t_extract
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except OSError:
            pass

    audio_duration = len(samples) / 16_000
    recognizer = get_recognizer(quantize=QUANTIZE, num_threads=NUM_THREADS)

    t0 = time.perf_counter()
    text = transcribe_samples(recognizer, samples)
    asr_elapsed = time.perf_counter() - t0
    total_elapsed = extract_elapsed + asr_elapsed

    logger.info(
        "transcribe/video  file=%s  duration=%.1fs  extract=%.0fms  asr=%.0fms  text=%r",
        file.filename, audio_duration, extract_elapsed * 1000, asr_elapsed * 1000, text[:80],
    )

    response = _build_response(text, total_elapsed, audio_duration, translate or AUTO_TRANSLATE)
    response["extract_latency_ms"] = round(extract_elapsed * 1000, 1)
    response["asr_latency_ms"] = round(asr_elapsed * 1000, 1)
    return response


@app.get("/health", summary="Service health check")
async def health():
    """Returns service status and model configuration."""
    return {
        "status": "ok",
        "service": "asr-service",
        "model": "gipformer-65M-rnnt",
        "quantize": QUANTIZE,
        "num_threads": NUM_THREADS,
        "translator_available": translator_available(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
