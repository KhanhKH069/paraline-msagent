"""
services/api-gateway/pipeline.py
Audio pipeline orchestrator.
Vexa pattern: routes audio through transcription-service → custom steps.

Inbound  pipeline: Audio → Whisper → NLLB → Piper → [subtitle + TTS audio]
Outbound pipeline: Audio → Whisper → NLLB → [Teams text]
"""
import asyncio
import logging
import os
import re
import time
from typing import Optional

import httpx
from fastapi import WebSocket

logger = logging.getLogger("meeting_ai.pipeline")

WHISPERLIVE_URL = os.getenv("WHISPERLIVE_URL",  "http://whisperlive:8001")
TRANSLATION_URL = os.getenv("TRANSLATION_URL",  "http://translation-service:8002")
TTS_URL         = os.getenv("TTS_URL",          "http://tts-service:8003")
COLLECTOR_URL   = os.getenv("COLLECTOR_URL",    "http://transcription-collector:8006")

# Shared async HTTP client (connection pooling). Set high timeout because CPU processing takes time.
_client = httpx.AsyncClient(timeout=300.0, limits=httpx.Limits(max_connections=50))

# Map mã ngôn ngữ từ Whisper/Qwen sang chuẩn NLLB-200
WHISPER_TO_NLLB = {
    "ja": "jpn_Jpan", "japanese": "jpn_Jpan", "jpn": "jpn_Jpan",
    "en": "eng_Latn", "english": "eng_Latn", "eng": "eng_Latn",
    "vi": "vie_Latn", "vietnamese": "vie_Latn", "vie": "vie_Latn",
    "zh": "zho_Hans", "chinese": "zho_Hans", "zho": "zho_Hans", "mandarin": "zho_Hans",
    "ko": "kor_Hang", "korean": "kor_Hang", "kor": "kor_Hang",
    "fr": "fra_Latn", "french": "fra_Latn", "fra": "fra_Latn",
    "de": "deu_Latn", "german": "deu_Latn", "deu": "deu_Latn",
    "es": "spa_Latn", "spanish": "spa_Latn", "spa": "spa_Latn",
    "ru": "rus_Cyrl", "russian": "rus_Cyrl", "rus": "rus_Cyrl",
}

def detect_cjk_lang(text: str) -> Optional[str]:
    """Nhận diện nhanh CJK nếu ASR trả về und hoặc thiếu"""
    if not text:
        return None
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
        return "jpn_Jpan"
    if re.search(r'[\uac00-\ud7af\u1100-\u11ff]', text):
        return "kor_Hang"
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zho_Hans"
    return None


class AudioPipeline:
    """Orchestrates audio processing. Now with stateful partial-result deduplication and auto-language detection."""

    def __init__(self):
        self._last_listening_text = {} # {session_id: str}

    async def process(
        self,
        frame: dict,
        session_id: str,
        direction: str,
        ws: WebSocket,
        is_final: bool = True,
    ):
        """Route audio frame through the appropriate pipeline."""
        t0 = time.perf_counter()
        try:
            audio_b64 = frame.get("data", "")
            src_lang  = frame.get("src_lang", "auto")
            tgt_lang  = frame.get("tgt_lang", "vie_Latn")

            if not audio_b64:
                return

            # ── Step 1: ASR (Faster-Whisper / Qwen3-ASR) ───────
            t_asr_start = time.perf_counter()
            asr = await _client.post(f"{WHISPERLIVE_URL}/transcribe", json={
                "audio_b64":  audio_b64,
                "language":   src_lang,   # "auto" hoặc NLLB code
                "vad_filter": True,
            })
            asr.raise_for_status()
            asr_res = asr.json()
            original_text = asr_res.get("text", "").strip()
            detected_lang = asr_res.get("language", "").lower()

            t_asr_end = time.perf_counter()
            asr_latency = (t_asr_end - t_asr_start) * 1000

            # Xác định ngôn ngữ nguồn hiệu dụng cho NLLB và tag hiển thị
            if src_lang == "auto" or not src_lang:
                cjk = detect_cjk_lang(original_text)
                if cjk:
                    effective_src_lang = cjk
                else:
                    effective_src_lang = WHISPER_TO_NLLB.get(detected_lang, "eng_Latn")
                display_tag = detected_lang.upper() if detected_lang and detected_lang != "und" else effective_src_lang[:2].upper()
            else:
                effective_src_lang = src_lang
                display_tag = src_lang[:2].upper()

            # --- DEBUG PRINT ---
            print(f"🎙️ [ASR RAW TEXT]: '{original_text}' | Detected: {detected_lang} → NLLB: {effective_src_lang}", flush=True)
            # -------------------

            # --- HYBRID STREAMING LOGIC ---
            if not is_final:
                # Deduplication: Skip if text hasn't changed
                last_text = self._last_listening_text.get(session_id, "")
                if original_text == last_text:
                    return

                self._last_listening_text[session_id] = original_text

                # Intermediary ASR result
                await ws.send_json({
                    "type": "listening",
                    "text": f"{original_text}"
                })
                return

            # Không có text (im lặng/nhiễu đã bị lọc) -> bỏ qua các bước sau
            if not original_text:
                self._last_listening_text.pop(session_id, None)
                return

            # Final ASR result - Proceed to translation
            self._last_listening_text.pop(session_id, None) # Clear on final
            await ws.send_json({
                "type": "listening",
                "text": f"[{display_tag}] {original_text}"
            })

            # ── Step 2: Translation (NLLB) ─────────────────────
            # Tối ưu: Nếu ngôn ngữ nguồn trùng ngôn ngữ đích thì không cần dịch
            if effective_src_lang == tgt_lang:
                translated_text = original_text
                nllb_latency = 0.0
            else:
                t_nllb_start = time.perf_counter()
                nllb = await _client.post(f"{TRANSLATION_URL}/translate", json={
                    "text":     original_text,
                    "src_lang": effective_src_lang,
                    "tgt_lang": tgt_lang,
                })
                nllb.raise_for_status()
                translated_text = nllb.json().get("translated_text", original_text)

                t_nllb_end = time.perf_counter()
                nllb_latency = (t_nllb_end - t_nllb_start) * 1000

            latency_ms = (time.perf_counter() - t0) * 1000

            # --- DEBUG TIMING PRINT ---
            print(f"⏱️ [TIMING] Nhận Audio -> ASR ({display_tag}): {asr_latency:.0f}ms | NLLB (Dịch): {nllb_latency:.0f}ms | Tổng: {latency_ms:.0f}ms", flush=True)
            # --------------------------

            display_orig = f"[{display_tag}] {original_text}"

            # ── Branch A — Inbound: return TTS audio + subtitle ─
            if direction == "inbound":
                tts_audio_b64 = await self._synthesize(translated_text)
                await ws.send_json({
                    "type":             "inbound_result",
                    "original_text":    display_orig,
                    "translated_text":  translated_text,
                    "detected_lang":    detected_lang,
                    "src_lang":         effective_src_lang,
                    "audio_b64":        tts_audio_b64,
                    "sample_rate":      22050,
                    "latency_ms":       round(latency_ms, 1),
                })
                # Dedicated subtitle frame (client shows overlay)
                await ws.send_json({
                    "type":       "subtitle",
                    "text":       translated_text,
                    "latency_ms": round(latency_ms, 1),
                })

            # ── Branch B — Outbound: return text for Teams chat ─
            elif direction == "outbound":
                await ws.send_json({
                    "type":             "outbound_result",
                    "original_text":    display_orig,
                    "translated_text":  translated_text,
                    "detected_lang":    detected_lang,
                    "src_lang":         effective_src_lang,
                    "tgt_lang":         tgt_lang,
                    "push_to_teams":    True,
                    "latency_ms":       round(latency_ms, 1),
                })

            logger.info(
                f"[{session_id[:8]}] {direction} {latency_ms:.0f}ms "
                f"| [{display_tag}] {original_text[:40]} → {translated_text[:40]}"
            )

            # ── Async: store segment in DB via collector ────────
            asyncio.create_task(self._store_segment(
                session_id, direction, original_text, translated_text,
                effective_src_lang, tgt_lang, latency_ms,
            ))

        except httpx.HTTPStatusError as e:
            logger.error(f"Pipeline HTTP {e.response.status_code}: {e}")
            await ws.send_json({"type": "error", "message": f"Service error: {e.response.status_code}"})
        except Exception as e:
            logger.error(f"Pipeline error [{session_id[:8]}]: {e}", exc_info=True)
            await ws.send_json({"type": "error", "message": str(e)})

    async def _synthesize(self, text: str) -> Optional[str]:
        """TTS → base64 WAV. Returns None on failure (silent fallback)."""
        try:
            resp = await _client.post(f"{TTS_URL}/synthesize", json={"text": text})
            resp.raise_for_status()
            return resp.json().get("audio_b64")
        except Exception as e:
            logger.warning(f"TTS failed (silent fallback): {e}")
            return None

    async def _store_segment(
        self, session_id, direction, original, translated,
        src_lang, tgt_lang, latency_ms
    ):
        """Non-blocking: persist transcript segment to DB."""
        try:
            await _client.post(f"{COLLECTOR_URL}/segments", json={
                "session_id":      session_id,
                "direction":       direction,
                "original_text":   original,
                "translated_text": translated,
                "src_lang":        src_lang,
                "tgt_lang":        tgt_lang,
                "latency_ms":      latency_ms,
            })
        except Exception:
            pass  # Non-critical: transcript collection failure shouldn't break audio
