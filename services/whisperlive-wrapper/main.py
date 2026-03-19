"""
services/whisperlive-wrapper/main.py
Faster-Whisper ASR Service.
Vexa pattern: WhisperLive / transcription-service.

POST /transcribe  →  { text, language, segments, latency_ms }
"""
import base64
import logging
import os
import time

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel

logger = logging.getLogger("paraline.whisperlive")

MODEL_SIZE   = os.getenv("WHISPER_MODEL",        "large-v3")
DEVICE       = os.getenv("WHISPER_DEVICE",       "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
MODEL_DIR    = os.getenv("MODEL_CACHE_DIR",      "/models/whisper")

# If set, skip real ASR and return this text directly (for audio mock testing)
MOCK_TRANSCRIPTION_TEXT = os.getenv("MOCK_TRANSCRIPTION_TEXT", "")

_MOCK_PHRASES = [
    "Hello everyone, today we will discuss the project timeline.",
    "The development team has finished the first phase.",
    "We need to review the requirements before the next sprint.",
    "Please share your feedback on the current design proposal.",
    "The meeting will wrap up with a summary of action items.",
]
_mock_idx = 0

logger.info(f"Loading Whisper {MODEL_SIZE} on {DEVICE} ({COMPUTE_TYPE})...")
_model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, download_root=MODEL_DIR)
logger.info("✅ Whisper loaded")

app = FastAPI(title="Paraline WhisperLive")


class TranscribeReq(BaseModel):
    audio_b64: str
    language: str = "ja"       # Whisper language code (ja/en/vi/auto)
    sample_rate: int = 16000
    beam_size: int = 5
    vad_filter: bool = True


class TranscribeResp(BaseModel):
    text: str
    language: str
    latency_ms: float
    segments: list = []


@app.post("/transcribe", response_model=TranscribeResp)
async def transcribe(req: TranscribeReq):
    global _mock_idx
    t0 = time.perf_counter()

    # ── Mock bypass (set MOCK_TRANSCRIPTION_TEXT=__cycle__ in .env) ───────
    mock_text = os.getenv("MOCK_TRANSCRIPTION_TEXT", "")
    if mock_text == "__cycle__":
        text = _MOCK_PHRASES[_mock_idx % len(_MOCK_PHRASES)]
        _mock_idx += 1
        ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[mock] returning preset phrase: {text[:60]}")
        return TranscribeResp(text=text, language=req.language, latency_ms=round(ms, 1), segments=[])
    elif mock_text:
        ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[mock] returning fixed text: {mock_text[:60]}")
        return TranscribeResp(text=mock_text, language=req.language, latency_ms=round(ms, 1), segments=[])

    # ── Real ASR ──────────────────────────────────────────────────────────
    try:
        audio_np = np.frombuffer(base64.b64decode(req.audio_b64), dtype=np.float32)

        segments_gen, info = _model.transcribe(
            audio_np,
            language=req.language if req.language != "auto" else None,
            beam_size=req.beam_size,
            vad_filter=req.vad_filter,
            vad_parameters={"min_silence_duration_ms": 250},
            condition_on_previous_text=False,
            initial_prompt="Đây là nội dung cuộc họp: alo, xin chào, vâng."
        )

        segs = list(segments_gen)
        valid_segs = [s for s in segs if s.no_speech_prob < 0.8]
        text = " ".join(s.text.strip() for s in valid_segs).strip()

        # Filter common YouTube hallucinations
        lower_t = text.lower()
        if "subscribe" in lower_t or "đăng ký kênh" in lower_t or "ghiền mì gõ" in lower_t:
            text = ""

        ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"ASR [{info.language}] {ms:.0f}ms: {text[:60]}")

        return TranscribeResp(
            text=text,
            language=info.language,
            latency_ms=round(ms, 1),
            segments=[{"start": s.start, "end": s.end, "text": s.text} for s in segs],
        )
    except Exception as e:
        logger.error(f"ASR error: {e}", exc_info=True)
        raise HTTPException(500, str(e))



@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
