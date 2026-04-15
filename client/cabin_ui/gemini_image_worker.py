"""
gemini_image_worker.py
─────────────────────
QThread gọi Google Gemini 2.0 Flash để OCR + dịch ảnh sang tiếng Việt.
Emit kết quả về main thread qua signal — không block UI.

Dùng trong:
    main_window.py → _on_image_paste()
"""

import base64
import io
import json
import logging
import os
import urllib.request
import urllib.error

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("paraline.gemini")

GEMINI_MODEL   = "gemini-2.0-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


class GeminiImageWorker(QThread):
    """
    Worker dịch ảnh qua Gemini Vision API.

    Signals:
        result_ready (dict)  — dict với keys: detected_language, original_text, vietnamese_translation
        error_occurred (str) — thông báo lỗi nếu thất bại
    """

    result_ready   = pyqtSignal(object)   # dict hoặc str
    error_occurred = pyqtSignal(str)

    def __init__(self, pil_img, src_lang: str = "auto", api_key: str = "", parent=None):
        super().__init__(parent)
        self._pil_img  = pil_img
        self._src_lang = src_lang
        self._api_key  = api_key or os.getenv("GEMINI_API_KEY", "")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        try:
            result = self._call_gemini()
            self.result_ready.emit(result)
        except Exception as e:
            logger.exception("[GeminiWorker] Lỗi không xử lý được")
            self.error_occurred.emit(str(e))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call_gemini(self) -> dict:
        if not self._api_key:
            raise RuntimeError(
                "Chưa có GEMINI_API_KEY.\n"
                "Thêm vào file .env: GEMINI_API_KEY=AIzaSy...\n"
                "Lấy key miễn phí tại: https://aistudio.google.com/apikey"
            )

        # PIL → base64 PNG
        buf = io.BytesIO()
        self._pil_img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        lang_hint = (
            f" Ngôn ngữ nguồn là {self._src_lang}."
            if self._src_lang and self._src_lang != "auto"
            else ""
        )

        prompt = (
            f"Bạn là chuyên gia OCR và dịch thuật chuyên nghiệp.{lang_hint}\n\n"
            "Nhiệm vụ:\n"
            "1. Trích xuất TOÀN BỘ văn bản trong ảnh, giữ nguyên cấu trúc và xuống dòng.\n"
            "2. Dịch toàn bộ sang tiếng Việt tự nhiên, trôi chảy, đúng ngữ cảnh.\n\n"
            "Trả về JSON hợp lệ (không có markdown, không có backtick, không có text ngoài JSON):\n"
            '{"detected_language":"tên ngôn ngữ phát hiện","original_text":"toàn bộ văn bản gốc","vietnamese_translation":"bản dịch tiếng Việt"}\n\n'
            'Nếu ảnh không có văn bản: {"detected_language":"Không có văn bản","original_text":"(ảnh không chứa văn bản)","vietnamese_translation":"(không có gì để dịch)"}'
        )

        payload = json.dumps({
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            },
        }).encode()

        url = f"{GEMINI_ENDPOINT}?key={self._api_key}"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                err_msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                err_msg = body
            status = e.code
            if status == 400:
                raise RuntimeError(f"API key không hợp lệ hoặc sai định dạng (400): {err_msg}")
            elif status == 403:
                raise RuntimeError(f"API key bị từ chối (403): {err_msg}")
            elif status == 429:
                raise RuntimeError("Đã vượt giới hạn request (429). Chờ vài giây rồi thử lại.")
            else:
                raise RuntimeError(f"Lỗi Gemini API ({status}): {err_msg}")

        raw = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        clean = raw.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            # Nếu model không trả JSON chuẩn, trả text thô
            return {
                "detected_language": "Không xác định",
                "original_text": raw,
                "vietnamese_translation": "(Không parse được JSON — xem Original Text)",
            }
