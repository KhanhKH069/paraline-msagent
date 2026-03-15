"""
services/translation-service/main.py
NLLB-200 Machine Translation.

POST /translate        → single text
POST /translate/batch  → list of texts (dùng cho vision pipeline)
"""
import logging
import os
import time
from typing import List

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

logger = logging.getLogger("paraline.nllb")

MODEL_NAME = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")
CACHE_DIR  = os.getenv("MODEL_CACHE_DIR", "/models/nllb")

logger.info(f"Loading NLLB: {MODEL_NAME}")
_tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
_model     = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)
_device    = "cuda" if torch.cuda.is_available() else "cpu"
_model.to(_device)
logger.info(f"✅ NLLB loaded on {_device}")

app = FastAPI(title="Paraline Translation Service")


class TransReq(BaseModel):
    text: str
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"


class TransResp(BaseModel):
    translated_text: str
    src_lang: str
    tgt_lang: str
    latency_ms: float


class BatchReq(BaseModel):
    texts: List[str]
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"


class BatchResp(BaseModel):
    translations: List[str]
    latency_ms: float


@app.post("/translate", response_model=TransResp)
async def translate(req: TransReq):
    t0 = time.perf_counter()
    try:
        result = _translate(req.text, req.src_lang, req.tgt_lang)
        ms = (time.perf_counter() - t0) * 1000
        return TransResp(translated_text=result, src_lang=req.src_lang, tgt_lang=req.tgt_lang, latency_ms=round(ms, 1))
    except Exception as e:
        logger.error(f"Translation error: {e}")
        raise HTTPException(500, str(e))


@app.post("/translate/batch", response_model=BatchResp)
async def translate_batch(req: BatchReq):
    """Batch translation — critical for vision pipeline (many OCR blocks)."""
    t0 = time.perf_counter()
    try:
        results = [_translate(t, req.src_lang, req.tgt_lang) for t in req.texts]
        ms = (time.perf_counter() - t0) * 1000
        return BatchResp(translations=results, latency_ms=round(ms, 1))
    except Exception as e:
        raise HTTPException(500, str(e))


def _translate(text: str, src: str, tgt: str, max_len: int = 512) -> str:
    if not text.strip():
        return text
    _tokenizer.src_lang = src
    inputs = _tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(_device)
    forced_bos = _tokenizer.lang_code_to_id[tgt]
    outputs = _model.generate(**inputs, forced_bos_token_id=forced_bos, max_length=max_len, num_beams=4)
    return _tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "device": _device}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
