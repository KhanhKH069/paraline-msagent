"""
client/cabin_ui/rest_client.py
CabinRestClient — thay thế ParalineWSClient cho bộ Cabin UI (CPU-only).

Luồng:
  audio_b64 ──► POST :8005/transcribe  (Gipformer ONNX)
                    │ transcript (vi)
                    ▼
               POST :8002/translate    (NLLB-200)
                    │ translated_text (en/ja)
                    ▼
          on_subtitle(vi, en, latency_ms)   ← cập nhật UI ngay
                    │
                    ▼
               POST :8003/synthesize   (Piper TTS)
                    │ audio_b64 (wav)
                    ▼
          on_inbound_audio(audio_b64)        ← phát ra loa

Các hàm on_* chạy trên worker thread → cần thread-safe khi emit PyQt signal.
"""

import logging
import os
import queue
import threading
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger("paraline.cabin.rest")

ASR_URL         = os.getenv("CABIN_ASR_URL",   "http://127.0.0.1:8005")
NLLB_URL        = os.getenv("CABIN_NLLB_URL",  "http://127.0.0.1:8002")
TTS_URL         = os.getenv("CABIN_TTS_URL",   "http://127.0.0.1:8003")

# Ngôn ngữ mặc định cabin
DEFAULT_SRC_LANG = os.getenv("CABIN_SRC_LANG", "vie_Latn")   # tiếng nguồn (từ mic)
DEFAULT_TGT_LANG = os.getenv("CABIN_TGT_LANG", "eng_Latn")   # tiếng đích (dịch sang)


class CabinRestClient:
    """
    Đối tượng thay thế ParalineWSClient trong cabin_ui/main_window.py.

    API tối thiểu tương thích:
        .start()
        .stop()
        .send_inbound_chunk(pcm_b64: str)   ← AudioManager gọi hàm này
        .inbound_src_lang  (str, có thể ghi)   ← UI combo-box đổi ngôn ngữ
        .inbound_only = True                ← mặc định, chỉ Inbound
    """

    inbound_only = True  # giữ ký hiệu tương thích với main_window.py

    def __init__(
        self,
        # Các tham số này giữ cùng signature với ParalineWSClient để main_window không phải thay đổi nhiều
        server_ws_url: str = "",          # không dùng — giữ ký hiệu tương thích
        session_id: str = "",
        api_key: str = "",
        on_subtitle:      Optional[Callable[[str, str, float], None]] = None,
        on_inbound_audio: Optional[Callable[[str], None]] = None,
        on_outbound_text: Optional[Callable[[str, str], None]] = None,
        on_error:         Optional[Callable[[str], None]] = None,
        tgt_lang: str = DEFAULT_TGT_LANG,
    ):
        self._on_subtitle      = on_subtitle
        self._on_inbound_audio = on_inbound_audio
        self._on_error         = on_error

        self.inbound_src_lang  = DEFAULT_SRC_LANG    # Gipformer nhận Việt, luôn fix
        self.inbound_tgt_lang  = tgt_lang            # NLLB đích (eng / jpn …)

        # Worker queue — giữ tối đa 20 câu, tránh tắc nghẽn khi CPU chậm
        self._audio_q: queue.Queue = queue.Queue(maxsize=20)
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Chống hiển thị câu trùng lặp
        self._last_transcript = ""

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            name="CabinRestWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("[Cabin] CabinRestClient started — Gipformer → NLLB → Piper")
        print("[🛖 Cabin] REST pipeline started: Gipformer → NLLB → Piper", flush=True)

    def stop(self):
        self._running = False
        # Gửi sentinel để unblock queue.get()
        try:
            self._audio_q.put_nowait(None)
        except queue.Full:
            pass
        logger.info("[Cabin] CabinRestClient stopped")

    def send_inbound_chunk(self, pcm_b64: str):
        """Gọi bởi AudioManager mỗi khi có một câu hoàn chỉnh."""
        try:
            self._audio_q.put_nowait(pcm_b64)
        except queue.Full:
            # Drop câu cũ nhất để ưu tiên câu mới hơn
            try:
                self._audio_q.get_nowait()
                self._audio_q.put_nowait(pcm_b64)
            except (queue.Empty, queue.Full):
                pass

    # send_outbound_chunk: bỏ qua (cabin chỉ inbound)
    def send_outbound_chunk(self, pcm_b64: str):
        pass

    # ──────────────────────────────────────────────────────────
    # Worker Thread
    # ──────────────────────────────────────────────────────────

    def _worker(self):
        """Worker liên tục gọi ASR → NLLB → TTS theo thứ tự."""
        while self._running:
            try:
                pcm_b64 = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if pcm_b64 is None:  # sentinel stop
                break

            t0 = time.perf_counter()
            try:
                # ── Bước 1: Gipformer ASR ────────────────────────────
                transcript = self._call_asr(pcm_b64)
                if not transcript:
                    continue

                # Bỏ qua câu trùng lặp liên tiếp
                if transcript == self._last_transcript:
                    continue
                self._last_transcript = transcript

                asr_ms   = (time.perf_counter() - t0) * 1000
                print(f"[🎙️ Gipformer] {transcript!r}  ({asr_ms:.0f}ms)", flush=True)

                # ── Bước 2: NLLB Translation ─────────────────────────
                t_nllb = time.perf_counter()
                translated = self._call_nllb(
                    transcript,
                    src=self.inbound_src_lang,
                    tgt=self.inbound_tgt_lang,
                )
                nllb_ms = (time.perf_counter() - t_nllb) * 1000
                total_ms = (time.perf_counter() - t0) * 1000

                print(
                    f"[🌐 NLLB]      {translated!r}  ({nllb_ms:.0f}ms | total={total_ms:.0f}ms)",
                    flush=True,
                )

                # ── Gửi tín hiệu cập nhật UI ─────────────────────────
                if self._on_subtitle:
                    try:
                        self._on_subtitle(transcript, translated, total_ms)
                    except Exception as e:
                        logger.error(f"[Cabin] on_subtitle error: {e}")

                # ── Bước 3: Piper TTS ────────────────────────────────
                audio_b64 = self._call_tts(translated)
                if audio_b64 and self._on_inbound_audio:
                    try:
                        self._on_inbound_audio(audio_b64)
                    except Exception as e:
                        logger.error(f"[Cabin] on_inbound_audio error: {e}")

            except Exception as e:
                logger.error(f"[Cabin] Pipeline error: {e}", exc_info=True)
                if self._on_error:
                    try:
                        self._on_error(str(e))
                    except Exception:
                        pass

    # ──────────────────────────────────────────────────────────
    # Service Callers
    # ──────────────────────────────────────────────────────────

    def _call_asr(self, pcm_b64: str) -> str:
        """
        Gọi POST /transcribe trên Gipformer ASR service.
        Payload: { audio_b64, sample_rate }
        Response: { transcript }
        """
        try:
            resp = requests.post(
                f"{ASR_URL}/transcribe",
                json={"audio_b64": pcm_b64, "sample_rate": 16000},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("transcript", "").strip()
        except requests.exceptions.ConnectionError:
            logger.warning("[Cabin] ASR service không kết nối được — đang kiểm tra cổng 8005")
            return ""
        except Exception as e:
            logger.error(f"[Cabin] ASR error: {e}")
            return ""

    def _call_nllb(self, text: str, src: str, tgt: str) -> str:
        """Gọi POST /translate trên NLLB translation service."""
        try:
            resp = requests.post(
                f"{NLLB_URL}/translate",
                json={"text": text, "src_lang": src, "tgt_lang": tgt},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("translated_text", text).strip()
        except requests.exceptions.ConnectionError:
            logger.warning("[Cabin] NLLB service không kết nối được — cổng 8002")
            return text  # fallback: trả nguyên văn bản gốc
        except Exception as e:
            logger.error(f"[Cabin] NLLB error: {e}")
            return text

    def _call_tts(self, text: str) -> Optional[str]:
        """Gọi POST /synthesize trên Piper TTS service. Trả về audio_b64 hoặc None."""
        if not text.strip():
            return None
        try:
            resp = requests.post(
                f"{TTS_URL}/synthesize",
                json={"text": text, "speed": 1.0},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("audio_b64")
        except requests.exceptions.ConnectionError:
            logger.warning("[Cabin] Piper TTS không kết nối được — cổng 8003. TTS bị tắt.")
            return None
        except Exception as e:
            logger.error(f"[Cabin] TTS error: {e}")
            return None
