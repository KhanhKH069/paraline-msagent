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
import time
from typing import Optional

import httpx
from fastapi import WebSocket

logger = logging.getLogger("paraline.pipeline")

WHISPERLIVE_URL = os.getenv("WHISPERLIVE_URL",  "http://whisperlive:8001")
TRANSLATION_URL = os.getenv("TRANSLATION_URL",  "http://translation-service:8002")
TTS_URL         = os.getenv("TTS_URL",          "http://tts-service:8003")
COLLECTOR_URL   = os.getenv("COLLECTOR_URL",    "http://transcription-collector:8006")

# Shared async HTTP client (connection pooling)
_client = httpx.AsyncClient(timeout=8.0, limits=httpx.Limits(max_connections=50))

# Whisper language code mapping
_LANG_MAP = {"jpn_Jpan": "ja", "eng_Latn": "en", "vie_Latn": "vi"}


class AudioPipeline:
    """Stateless pipeline — all state lives in session-manager/DB."""

    async def process(
        self,
        frame: dict,
        session_id: str,
        direction: str,
        ws: WebSocket,
    ):
        """Route audio frame through the appropriate pipeline."""
        t0 = time.perf_counter()
        try:
            audio_b64 = frame.get("data", "")
            src_lang  = frame.get("src_lang", "jpn_Jpan")
            tgt_lang  = frame.get("tgt_lang", "vie_Latn")

            if not audio_b64:
                return

            # ── Step 1: ASR (Faster Whisper) ──────────────────
            asr = await _client.post(f"{WHISPERLIVE_URL}/transcribe", json={
                "audio_b64":  audio_b64,
                "language":   _LANG_MAP.get(src_lang),
                "vad_filter": True,
            })
            asr.raise_for_status()
            original_text = asr.json().get("text", "").strip()
            if not original_text:
                return  # Silence / no speech detected

            # Send immediate subtitle (original, pre-translation)
            # — gives user instant feedback that audio is received
            await ws.send_json({"type": "listening", "text": f"[{src_lang[:2].upper()}] {original_text[:60]}"})

            # ── Step 2: Translation (NLLB) ─────────────────────
            nllb = await _client.post(f"{TRANSLATION_URL}/translate", json={
                "text":     original_text,
                "src_lang": src_lang,
                "tgt_lang": tgt_lang,
            })
            nllb.raise_for_status()
            translated_text = nllb.json().get("translated_text", "")

            latency_ms = (time.perf_counter() - t0) * 1000

            # ── Branch A — Inbound: return TTS audio + subtitle ─
            if direction == "inbound":
                tts_audio_b64 = await self._synthesize(translated_text)
                await ws.send_json({
                    "type":             "inbound_result",
                    "original_text":    original_text,
                    "translated_text":  translated_text,
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
                    "original_text":    original_text,
                    "translated_text":  translated_text,
                    "tgt_lang":         tgt_lang,
                    "push_to_teams":    True,
                    "latency_ms":       round(latency_ms, 1),
                })

            logger.info(
                f"[{session_id[:8]}] {direction} {latency_ms:.0f}ms "
                f"| {original_text[:40]} → {translated_text[:40]}"
            )

            # ── Async: store segment in DB via collector ────────
            asyncio.create_task(self._store_segment(
                session_id, direction, original_text, translated_text,
                src_lang, tgt_lang, latency_ms,
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
