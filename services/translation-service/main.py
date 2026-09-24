"""
services/translation-service/main.py
NLLB-200 Machine Translation Service.

POST /translate        → single text
POST /translate/batch  → list of texts (dùng cho vision pipeline)
"""
import os
import re
import time
import logging
from typing import List

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Cấu hình Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meeting_ai.nllb")

# Cấu hình Model
MODEL_NAME = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")
CACHE_DIR = os.getenv("MODEL_CACHE_DIR", "/models/nllb")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

logger.info(f"🚀 Đang tải NLLB: {MODEL_NAME} trên {DEVICE}")

_tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, cache_dir=CACHE_DIR)

# Tối ưu cho GTX 1650: Dùng thẳng FLOAT16.
# Vì 2 model (Qwen 600M + NLLB 600M) cộng lại mới có 2.4GB, dùng FLOAT16 dư sức nằm gọn trong 4GB VRAM
# Tuyệt đối không dùng load_in_8bit vì card đời cũ không có Tensor Core giải mã INT8, khiến tốc độ dịch giật lag từ 3-7s/câu!
_model = AutoModelForSeq2SeqLM.from_pretrained(
    MODEL_NAME,
    cache_dir=CACHE_DIR,
    torch_dtype=torch.float16,
).to(DEVICE)

app = FastAPI(title="Meeting AI Translation Service")

# --- Models Pydantic ---
class TransReq(BaseModel):
    text: str
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"

class BatchReq(BaseModel):
    texts: List[str]
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"

# --- Logic Dịch Thuật Tối Ưu ---

def _detect_language(text: str) -> str:
    """Tự động nhận diện ngôn ngữ dựa trên đặc trưng bảng chữ cái/ký tự"""
    if not text:
        return "eng_Latn"
    # 1. Tiếng Nhật: Có Hiragana (\u3040-\u309F) hoặc Katakana (\u30A0-\u30FF)
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
        return "jpn_Jpan"
    # 2. Tiếng Hàn: Có ký tự Hangul (\uAC00-\uD7AF, \u1100-\u11FF)
    if re.search(r'[\uac00-\ud7af\u1100-\u11ff]', text):
        return "kor_Hang"
    # 3. Tiếng Trung: Có chữ Hán nhưng không có Hiragana/Katakana
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zho_Hans"
    # 4. Tiếng Việt: Có dấu tiếng Việt đặc trưng
    if re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', text, re.IGNORECASE):
        return "vie_Latn"
    # Mặc định chữ Latinh phổ biến nhất trong hội thoại/tài liệu quốc tế: Tiếng Anh
    return "eng_Latn"

def _normalize_src_lang(src: str, sample_text: str = "") -> str:
    """Đảm bảo src_lang luôn là mã NLLB hợp lệ, tuyệt đối không để lọt chuỗi 'auto'"""
    if not src or src.lower() == "auto" or src not in _tokenizer.lang_code_to_id:
        detected = _detect_language(sample_text)
        logger.info(f"🌐 [NLLB] src_lang='{src}' không hợp lệ hoặc là 'auto' -> Tự động nhận diện: {detected}")
        return detected
    return src

def _core_translate(texts: List[str], src: str, tgt: str) -> List[str]:
    """Hàm lõi xử lý dịch theo Batch thật sự trên GPU"""
    if not texts:
        return []

    # 1. Setup ngôn ngữ (Bảo vệ: Tuyệt đối không để 'auto' vào tokenizer)
    sample = texts[0] if texts else ""
    safe_src = _normalize_src_lang(src, sample)
    safe_tgt = tgt if tgt in _tokenizer.lang_code_to_id else "vie_Latn"

    _tokenizer.src_lang = safe_src
    forced_bos_id = _tokenizer.lang_code_to_id[safe_tgt]

    # 2. Tokenize (Padding giúp xử lý Batch song song)
    inputs = _tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512
    ).to(DEVICE)

    # 3. Sinh văn bản với cấu hình chống lặp và beam=2 cho câu văn mượt mà
    with torch.inference_mode(): # Nhanh hơn no_grad
        outputs = _model.generate(
            **inputs,
            forced_bos_token_id=forced_bos_id,
            max_new_tokens=128,
            num_beams=2,            # Beam search 2 cho câu dịch mượt và chuẩn nghĩa hơn rõ rệt
            repetition_penalty=1.1, # Chống lặp từ nhẹ nhàng, tránh cản trở câu tự nhiên
            no_repeat_ngram_size=3, # Ngăn lặp lại cụm 3 từ
            early_stopping=True
        )

    # 4. Decode kết quả
    decoded = _tokenizer.batch_decode(outputs, skip_special_tokens=True)
    return [_postprocess(t) for t in decoded]

# Bảng tinh chỉnh thuật ngữ / dị biệt dịch của NLLB sang tiếng Việt
GLOSSARY_REPLACEMENTS = [
    (re.compile(r"\bthịt xô\b", re.IGNORECASE), "bít tết"),
    (re.compile(r"\blàn da đeo\b", re.IGNORECASE), "để cả vỏ"),
    (re.compile(r"\blàn da bật\b", re.IGNORECASE), "để cả vỏ"),
]

def _postprocess(text: str) -> str:
    """Làm sạch rác và tinh chỉnh thuật ngữ sau khi dịch"""
    text = text.replace("▁", " ")
    # Xóa các code ngôn ngữ thừa nếu có
    text = re.sub(r"__[a-z]{3}_[A-Za-z]{4}__", "", text)
    # Áp dụng glossary tinh chỉnh
    for pattern, replacement in GLOSSARY_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    # Xử lý khoảng trắng thừa
    text = re.sub(r"\s+", " ", text).strip()
    return text

# --- Endpoints ---

@app.post("/translate")
async def translate(req: TransReq):
    t0 = time.perf_counter()
    try:
        # Xử lý như một batch có 1 phần tử để dùng chung logic
        results = _core_translate([req.text], req.src_lang, req.tgt_lang)
        ms = (time.perf_counter() - t0) * 1000
        return {
            "translated_text": results[0],
            "latency_ms": round(ms, 1)
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(500, str(e))

@app.post("/translate/batch")
async def translate_batch(req: BatchReq):
    """Dịch batch cực nhanh cho Vision Pipeline"""
    t0 = time.perf_counter()
    try:
        # Lọc bỏ text trống để tránh lỗi model
        valid_texts = [t if t.strip() else " " for t in req.texts]
        results = _core_translate(valid_texts, req.src_lang, req.tgt_lang)
        
        ms = (time.perf_counter() - t0) * 1000
        return {
            "translations": results,
            "latency_ms": round(ms, 1)
        }
    except Exception as e:
        logger.error(f"Batch Error: {e}")
        raise HTTPException(500, str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "device": DEVICE, "vram_allocated": f"{torch.cuda.memory_allocated() / 1024**2:.1f}MB"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)