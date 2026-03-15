"""
services/vision-service/main.py
Image Translation Pipeline — 5 bước:
  Step 1: Decode ảnh Base64
  Step 2: PaddleOCR → text blocks + bounding boxes
  Step 3: NLLB batch translate (gọi translation-service)
  Step 4: OpenCV TELEA inpainting → xóa chữ gốc, giữ nền
  Step 5: Pillow render → in chữ VN vừa bounding box (auto font size)

POST /translate/image  →  { translated_image_b64, ocr_blocks, latency_ms }
"""
import base64
import io
import logging
import os
import time
from typing import List, Tuple

import cv2
import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from PIL import Image, ImageDraw, ImageFont
from paddleocr import PaddleOCR
from pydantic import BaseModel

logger = logging.getLogger("paraline.vision")

OCR_LANG        = os.getenv("OCR_LANG", "japan")
TRANSLATION_URL = os.getenv("TRANSLATION_URL", "http://translation-service:8002")
FONT_PATH       = os.getenv("FONT_PATH", "/models/fonts/NotoSansCJK-Regular.ttc")

logger.info(f"Loading PaddleOCR lang={OCR_LANG}...")
_ocr = PaddleOCR(use_angle_cls=True, lang=OCR_LANG, use_gpu=False, show_log=False)
_http = httpx.Client(timeout=15.0)
logger.info("✅ PaddleOCR loaded")

app = FastAPI(title="Paraline Vision Service")


class ImgTransReq(BaseModel):
    session_id: str
    image_b64: str
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"
    font_auto_resize: bool = True


class OCRBlock(BaseModel):
    original_text: str
    translated_text: str
    bbox: List[List[int]]
    confidence: float


class ImgTransResp(BaseModel):
    translated_image_b64: str
    ocr_blocks: List[OCRBlock]
    total_latency_ms: float


@app.post("/translate/image", response_model=ImgTransResp)
async def translate_image(req: ImgTransReq):
    t0 = time.perf_counter()
    try:
        # ── Step 1: Decode ───────────────────────────────────
        pil_img = Image.open(io.BytesIO(base64.b64decode(req.image_b64))).convert("RGB")
        cv_img  = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        logger.info(f"Vision: image {pil_img.size}")

        # ── Step 2: OCR ──────────────────────────────────────
        blocks = _run_ocr(cv_img)
        if not blocks:
            logger.info("No text detected — returning original image")
            return ImgTransResp(
                translated_image_b64=req.image_b64,
                ocr_blocks=[],
                total_latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Step 3: Batch translate ──────────────────────────
        translations = _batch_translate([b["text"] for b in blocks], req.src_lang, req.tgt_lang)
        for i, b in enumerate(blocks):
            b["translated"] = translations[i]

        # ── Step 4: Inpainting (erase original text) ─────────
        clean_img = _inpaint(cv_img, blocks)

        # ── Step 5: Render Vietnamese text ───────────────────
        result_pil = Image.fromarray(cv2.cvtColor(clean_img, cv2.COLOR_BGR2RGB))
        result_pil = _render(result_pil, blocks, req.font_auto_resize)

        # ── Encode & return ───────────────────────────────────
        buf = io.BytesIO()
        result_pil.save(buf, format="PNG")
        out_b64 = base64.b64encode(buf.getvalue()).decode()

        ms = (time.perf_counter() - t0) * 1000
        logger.info(f"Vision pipeline: {ms:.0f}ms, {len(blocks)} blocks")

        return ImgTransResp(
            translated_image_b64=out_b64,
            ocr_blocks=[OCRBlock(
                original_text=b["text"],
                translated_text=b["translated"],
                bbox=b["bbox"],
                confidence=b["confidence"],
            ) for b in blocks],
            total_latency_ms=round(ms, 1),
        )
    except Exception as e:
        logger.error(f"Vision error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ─────────────────────────────────────────────
# Pipeline Steps
# ─────────────────────────────────────────────

def _run_ocr(cv_img: np.ndarray) -> List[dict]:
    """Step 2: PaddleOCR — returns list of {text, bbox, confidence}."""
    result = _ocr.ocr(cv_img, cls=True)
    blocks = []
    if not result or not result[0]:
        return blocks
    for line in result[0]:
        polygon, (text, conf) = line
        blocks.append({
            "text":       text,
            "bbox":       [[int(p[0]), int(p[1])] for p in polygon],
            "confidence": float(conf),
            "translated": "",
        })
    return blocks


def _batch_translate(texts: List[str], src: str, tgt: str) -> List[str]:
    """Step 3: Gọi translation-service batch endpoint."""
    try:
        r = _http.post(f"{TRANSLATION_URL}/translate/batch", json={
            "texts": texts, "src_lang": src, "tgt_lang": tgt,
        })
        r.raise_for_status()
        return r.json()["translations"]
    except Exception as e:
        logger.error(f"Batch translate failed: {e}")
        return texts  # Fallback: keep originals


def _inpaint(cv_img: np.ndarray, blocks: List[dict]) -> np.ndarray:
    """
    Step 4: Xóa chữ gốc bằng OpenCV TELEA inpainting.
    Tạo mask từ polygon bounding boxes, inflate 2px để chắc sạch.
    """
    mask = np.zeros(cv_img.shape[:2], dtype=np.uint8)
    for b in blocks:
        pts = np.array(b["bbox"], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
    # Dilate mask slightly to cover antialiased edges
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return cv2.inpaint(cv_img, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)


def _render(pil_img: Image.Image, blocks: List[dict], auto_resize: bool) -> Image.Image:
    """
    Step 5: Pillow — in chữ VN vừa bounding box.
    Auto-resize font: tìm font size lớn nhất mà text không tràn khỏi bbox.
    """
    draw = ImageDraw.Draw(pil_img)
    for b in blocks:
        text = b.get("translated") or b["text"]
        xs = [p[0] for p in b["bbox"]]
        ys = [p[1] for p in b["bbox"]]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        bw, bh = x1 - x0, y1 - y0

        font_size = _fit_font(text, bw, bh) if auto_resize else max(bh, 8)
        font = _load_font(font_size)
        color = _contrast_color(np.array(pil_img)[y0:y1, x0:x1])
        draw.text((x0, y0), text, font=font, fill=color)
    return pil_img


def _fit_font(text: str, box_w: int, box_h: int) -> int:
    """Binary-search for largest font size that fits text in box_w x box_h."""
    lo, hi = 6, max(box_h, 8)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            f = _load_font(mid)
            bb = f.getbbox(text)
            if (bb[2] - bb[0]) <= box_w and (bb[3] - bb[1]) <= box_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        except Exception:
            break
    return best


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _contrast_color(region: np.ndarray) -> Tuple[int, int, int]:
    if region.size == 0:
        return (0, 0, 0)
    avg = float(np.mean(region))
    return (255, 255, 255) if avg < 128 else (20, 20, 20)


@app.get("/health")
async def health():
    return {"status": "ok", "ocr_lang": OCR_LANG}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8004)
