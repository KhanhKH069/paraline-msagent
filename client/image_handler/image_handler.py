"""
client/image_handler/image_handler.py
Quản lý luồng dịch ảnh slide.

- Capture vùng màn hình (Snipping Tool API)
- Nhận ảnh từ Clipboard (Ctrl+V)
- Gửi lên vision-service qua REST
- Nhận lại ảnh đã dịch
"""
import base64
import io
import logging
import os
from typing import Callable, Optional

import requests
from PIL import Image, ImageGrab

logger = logging.getLogger("paraline.image")

SERVER_REST = os.getenv("PARALINE_SERVER_REST", "http://192.168.1.100:8056")


class ImageHandler:
    def __init__(self, session_id: str, api_key: str = ""):
        self.session_id = session_id
        self.api_key    = api_key

    # ─────────────────────────────────────────────
    # Capture
    # ─────────────────────────────────────────────

    def grab_clipboard(self) -> Optional[Image.Image]:
        """Lấy ảnh từ clipboard (Ctrl+V / Snipping Tool)."""
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                return img
        except Exception as e:
            logger.error(f"Clipboard grab error: {e}")
        return None

    def grab_region(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """Chụp một vùng màn hình cụ thể."""
        return ImageGrab.grab(bbox=(x, y, x + w, y + h))

    # ─────────────────────────────────────────────
    # Translate
    # ─────────────────────────────────────────────

    def translate_image(
        self,
        pil_image: Image.Image,
        src_lang: str = "jpn_Jpan",
        tgt_lang: str = "vie_Latn",
        on_success: Optional[Callable[[Image.Image, list], None]] = None,
        on_error:   Optional[Callable[[str], None]] = None,
    ):
        """
        Gửi ảnh lên server để dịch.
        Chạy trong thread riêng để không block UI.
        on_success(result_image: PIL.Image, ocr_blocks: list)
        """
        import threading

        def _worker():
            try:
                b64 = self._pil_to_b64(pil_image)
                resp = requests.post(
                    f"{SERVER_REST}/translate/image",
                    json={
                        "session_id": self.session_id,
                        "image_b64":  b64,
                        "src_lang":   src_lang,
                        "tgt_lang":   tgt_lang,
                    },
                    headers={"X-API-Key": self.api_key},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                result_img = self._b64_to_pil(data["translated_image_b64"])
                if on_success:
                    on_success(result_img, data.get("ocr_blocks", []))

            except Exception as e:
                logger.error(f"Image translate error: {e}")
                if on_error:
                    on_error(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────
    # Utils
    # ─────────────────────────────────────────────

    @staticmethod
    def _pil_to_b64(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _b64_to_pil(b64: str) -> Image.Image:
        return Image.open(io.BytesIO(base64.b64decode(b64)))
