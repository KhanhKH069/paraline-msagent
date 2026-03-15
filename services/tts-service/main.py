"""
services/tts-service/main.py
Piper TTS — Vietnamese text → WAV audio.

POST /synthesize  →  { audio_b64, sample_rate, latency_ms }
"""
import base64
import logging
import os
import struct
import subprocess
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("paraline.tts")

VOICE     = os.getenv("PIPER_VOICE", "vi_VN-vivos-medium")
MODEL_DIR = os.getenv("MODEL_CACHE_DIR", "/models/piper")
SR        = int(os.getenv("SAMPLE_RATE", "22050"))

app = FastAPI(title="Paraline TTS Service")


class SynthReq(BaseModel):
    text: str
    speed: float = 1.0


class SynthResp(BaseModel):
    audio_b64: str
    sample_rate: int
    latency_ms: float


@app.post("/synthesize", response_model=SynthResp)
async def synthesize(req: SynthReq):
    t0 = time.perf_counter()
    try:
        model_path  = f"{MODEL_DIR}/{VOICE}.onnx"
        config_path = f"{MODEL_DIR}/{VOICE}.json"
        length_scale = str(round(1.0 / max(req.speed, 0.1), 3))

        proc = subprocess.run(
            ["piper", "--model", model_path, "--config", config_path,
             "--length-scale", length_scale, "--output-raw"],
            input=req.text.encode("utf-8"),
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Piper: {proc.stderr.decode()[:200]}")

        wav_bytes = _pcm_to_wav(proc.stdout, SR)
        audio_b64 = base64.b64encode(wav_bytes).decode()
        ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"TTS {ms:.0f}ms: {req.text[:40]}")
        return SynthResp(audio_b64=audio_b64, sample_rate=SR, latency_ms=round(ms, 1))
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(500, str(e))


def _pcm_to_wav(pcm: bytes, sr: int) -> bytes:
    """Wrap raw 16-bit PCM in a WAV container."""
    ch, bps = 1, 16
    data_sz = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_sz, b"WAVE", b"fmt ", 16,
        1, ch, sr, sr * ch * bps // 8, ch * bps // 8, bps, b"data", data_sz,
    )
    return header + pcm


@app.get("/health")
async def health():
    return {"status": "ok", "voice": VOICE}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
