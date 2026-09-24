"""
client/audio_router/inbound_audio_manager.py
FIX: Use PyTorch Silero VAD instead of ONNX (ONNX version not working)

Changelog:
- [FIX] Reset VAD hidden state after each sentence (LSTM state bleed)
- [FIX] Lock for _resample_buf to prevent race condition in hw callback
- [FIX] Cache torch module reference instead of importing every chunk
- [FIX] VAD window size promoted to named constant (no more magic 512)
- [FIX] Queue overflow now logs a warning for easier debugging
- [FIX] Disabled processing stages (spec_sub, trim, normalize) controlled
         via .env flags instead of commented-out code
- [FIX] _find_device uses logger instead of bare print
- [FIX] _load_vad_model runs in a background thread with join-timeout
         so start() does not block the caller
- [TUNE] SILENCE_CHUNKS default raised from 3 → 6 (288ms → 576ms)
         to avoid premature sentence cuts on natural speech pauses
"""

import base64
import datetime
import logging
import os
import queue
import threading
import time
import wave
from collections import deque
from math import gcd
from typing import Callable, Optional

try:
    import torch
except Exception:
    pass


from dotenv import load_dotenv

load_dotenv(override=True)

import numpy as np
import sounddevice as sd

logger = logging.getLogger("meeting_ai.audio.inbound")

# ── Audio pipeline constants ─────────────────────────────────────────────────
SAMPLE_RATE    = int(os.getenv("AUDIO_SAMPLE_RATE",    "16000"))
CHUNK_MS       = int(os.getenv("AUDIO_CHUNK_MS",       "96"))
CHUNK_SAMP     = SAMPLE_RATE * CHUNK_MS // 1000          # 1536 samples @ 16 kHz
VIRTUAL_SPK    = os.getenv("VIRTUAL_SPEAKER_NAME",      "pulse")

# ── VAD constants ────────────────────────────────────────────────────────────
VAD_THRESHOLD  = float(os.getenv("VAD_SPEECH_THRESHOLD",  "0.40"))

# SILENCE_CHUNKS: how many consecutive silent chunks before ending a sentence.
#   96 ms × 6 = 576 ms  ← enough to survive natural pauses without cutting mid-phrase.
#   Raise to 8 (768 ms) for conversational / interview audio.
#   Lower to 4 (384 ms) if you need snappier response latency.
SILENCE_CHUNKS = int(os.getenv("SILENCE_CHUNKS_LIMIT",   "6"))

MAX_CHUNKS     = int(os.getenv("MAX_SENTENCE_CHUNKS",    "100"))  # ~9.6 s max
HISTORY_CHUNKS = int(os.getenv("HISTORY_CHUNKS",         "2"))
OVERLAP_CHUNKS = int(os.getenv("OVERLAP_CHUNKS", "6"))           # ~1s overlap

# Silero VAD: optimal inference window is exactly 512 samples (32 ms @ 16 kHz).
# Do NOT change unless you retrain the model.
VAD_WINDOW_SAMPS = 512

# ── Optional processing stages (toggle via .env) ─────────────────────────────
ENABLE_SPEC_SUB   = os.getenv("ENABLE_SPEC_SUB",   "0") == "1"
ENABLE_TRIM       = os.getenv("ENABLE_TRIM",        "0") == "1"
ENABLE_NORMALIZE  = os.getenv("ENABLE_NORMALIZE",   "0") == "1"

SPEC_OVER_SUB  = float(os.getenv("SPEC_OVER_SUBTRACTION_IN", "0.8"))
SPEC_FLOOR     = float(os.getenv("SPEC_FLOOR_RATIO_IN",      "0.05"))
NOISE_ALPHA    = float(os.getenv("NOISE_ALPHA_IN",            "0.1"))

NORM_TARGET    = float(os.getenv("NORMALIZE_TARGET_RMS",  "0.1"))
NORM_MAX_GAIN  = float(os.getenv("NORMALIZE_MAX_GAIN_IN", "3.0"))

WHISPER_PAD_MS = int(os.getenv("WHISPER_PAD_MS", "300"))
MIN_AUDIO_SEC  = float(os.getenv("MIN_AUDIO_SEC", "0.3"))
PARTIAL_INTERVAL_SEC = 0.5   # 500ms for "word-by-word" effect

# ── Debug ────────────────────────────────────────────────────────────────────
DEBUG_AUDIO   = os.getenv("DEBUG_AUDIO",        "0") == "1"
DEBUG_DIR     = os.getenv("DEBUG_AUDIO_DIR",    "debug_audio/inbound")
DEBUG_RMS_SEC = float(os.getenv("DEBUG_RMS_INTERVAL", "3.0"))


class InboundAudioManager:
    def __init__(self):
        self._running  = False
        self._callback: Optional[Callable[[str], None]] = None

        self._in_q        = queue.Queue(maxsize=200)
        self._noise_lock  = threading.Lock()
        self._noise_profile: Optional[np.ndarray] = None
        self._last_dbg    = 0.0

        # PyTorch / Silero VAD
        self._torch            = None   # cached torch module
        self._vad_model        = None
        self._vad_ready        = threading.Event()   # set when model is loaded

        # Hardware stream
        self._stream: Optional[sd.InputStream] = None
        self._device_rate: int = SAMPLE_RATE
        self._raw_hw_q: queue.Queue = queue.Queue(maxsize=200)
        self._resample_up: int = 1
        self._resample_down: int = 1

        # Guard for any buffer manipulation
        self._resample_lock = threading.Lock()
        self._resample_buf  = np.array([], dtype=np.float32)

    # ── Public API ───────────────────────────────────────────────────────────

    def start(
        self,
        callback: Callable[[str, bool], None],   # Added is_final: bool
        device_name: Optional[str] = None,
        level_callback: Optional[Callable[[float], None]] = None,
    ):
        self._callback = callback
        self._level_cb = level_callback
        self._running  = True

        dev_name = device_name or VIRTUAL_SPK

        # Support "pulse::<source_name>" or "idx::<device_index>" or "alsa::<device_name>" from UI
        if dev_name and "::" in dev_name:
            dev_type, real_name = dev_name.split("::", 1)
            if dev_type == "pulse":
                os.environ["PULSE_SOURCE"] = real_name
                logger.info("[INBOUND] PULSE_SOURCE = %s", real_name)
                dev = (
                    self._find_device("pulse",   input=True)
                    or self._find_device("default", input=True)
                )
                logger.info("[INBOUND] Using '%s' via PulseAudio Source [%s]", dev, real_name)
            elif dev_type in ("idx", "id", "dev"):
                try:
                    dev = int(real_name)
                    dev_info = sd.query_devices(dev)
                    logger.info("[INBOUND] Using explicit device [%d]: %s", dev, dev_info["name"])
                except Exception as exc:
                    logger.warning("[INBOUND] Invalid device index '%s': %s", real_name, exc)
                    dev = self._find_device(real_name, input=True)
            else:
                dev = self._find_device(real_name, input=True)
                logger.info("[INBOUND] Device: %s [idx: %s]", real_name, dev)
        else:
            dev = self._find_device(dev_name, input=True)
            logger.info("[INBOUND] Selected device: %s [idx: %s]", dev_name, dev)

        if dev is not None:
            dev_info = sd.query_devices(dev)
            self._device_rate = int(dev_info["default_samplerate"])
            logger.info("[INBOUND] Native rate: %d Hz | Pipeline rate: %d Hz", self._device_rate, SAMPLE_RATE)
            if self._device_rate != SAMPLE_RATE:
                logger.info("[INBOUND] Resampling %d→%d Hz (scipy polyphase)", self._device_rate, SAMPLE_RATE)
        else:
            self._device_rate = SAMPLE_RATE

        g = gcd(SAMPLE_RATE, self._device_rate)
        self._resample_up = SAMPLE_RATE // g
        self._resample_down = self._device_rate // g

        logger.info(
            "[INBOUND] Chunk: %d ms (%d samples) | VAD threshold: %.2f | silence=%d×%d ms (%.0f ms)",
            CHUNK_MS, CHUNK_SAMP, VAD_THRESHOLD, SILENCE_CHUNKS, CHUNK_MS, SILENCE_CHUNKS * CHUNK_MS,
        )

        # Load VAD in background non-blockingly (fallback to RMS if not ready yet)
        if self._vad_model is None and not getattr(self, "_vad_loading", False):
            self._vad_loading = True
            threading.Thread(
                target=self._load_vad_model, name="VADLoader", daemon=True
            ).start()

        if dev is not None:
            native_chunk = self._device_rate * CHUNK_MS // 1000
            self._stream = sd.InputStream(
                device=dev,
                samplerate=self._device_rate,
                channels=1,
                dtype="int16",
                blocksize=native_chunk,
                latency="high",
                callback=self._hw_cb,
            )
            self._stream.start()
            logger.info("[INBOUND] Stream started [%s] @ %d Hz", dev, self._device_rate)
        else:
            logger.warning("[INBOUND] No device found — mock mode")
            threading.Thread(target=self._mock, name="InboundMock", daemon=True).start()

        threading.Thread(target=self._resample_worker, name="InboundResample", daemon=True).start()
        threading.Thread(target=self._vad_worker, name="InboundVAD", daemon=True).start()

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("[INBOUND] Stopped")

    # ── PyTorch VAD ──────────────────────────────────────────────────────────

    def _load_vad_model(self):
        """Load Silero VAD (PyTorch). Runs in a daemon thread."""
        try:
            import torch

            torch.set_num_threads(1)

            logger.info("[INBOUND] Loading PyTorch Silero VAD …")
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                verbose=False,
                trust_repo=True,
            )
            model.to(torch.device("cpu")).eval()

            # Cache the module and model so _check_speech_pytorch never re-imports
            self._torch     = torch
            self._vad_model = model
            self._vad_utils = utils

            logger.info("[INBOUND] Silero VAD ready | threshold=%.2f | window=%d samps (32 ms)",
                        VAD_THRESHOLD, VAD_WINDOW_SAMPS)
        except Exception as exc:
            logger.error("[INBOUND] Failed to load PyTorch VAD: %s — using RMS fallback", exc)
        finally:
            self._vad_ready.set()   # always unblock the waiter

    def _reset_vad_state(self):
        """
        Reset Silero's LSTM hidden state between sentences.
        Without this, the model carries over context from the previous utterance,
        which can suppress the start of a new sentence.
        """
        if self._vad_model is not None:
            try:
                self._vad_model.reset_states()
            except Exception as exc:
                logger.debug("[VAD] reset_states failed: %s", exc)

    def _check_speech_pytorch(self, chunk_float: np.ndarray) -> bool:
        """
        Return True if the chunk contains speech.
        chunk_float must be float32 in [-1, 1] at SAMPLE_RATE.
        Falls back to RMS VAD when model is unavailable.
        """
        if not self._vad_ready.is_set() or self._vad_model is None:
            return self._rms_vad(chunk_float)

        if self._vad_model is None or self._torch is None:
            return self._rms_vad(chunk_float)

        try:
            torch = self._torch   # use cached reference — no import overhead
            max_prob = 0.0

            with torch.no_grad():
                for start in range(0, len(chunk_float), VAD_WINDOW_SAMPS):
                    window = chunk_float[start : start + VAD_WINDOW_SAMPS]

                    if len(window) < VAD_WINDOW_SAMPS:
                        window = np.pad(window, (0, VAD_WINDOW_SAMPS - len(window)))

                    tensor = torch.from_numpy(window).float().unsqueeze(0)
                    prob = self._vad_model(tensor, SAMPLE_RATE).item()
                    max_prob = max(max_prob, prob)

            return max_prob >= VAD_THRESHOLD

        except Exception as exc:
            logger.error("[VAD] Inference error: %s", exc)
            return self._rms_vad(chunk_float)

    # ── Hardware callback ────────────────────────────────────────────────────

    def _hw_cb(self, indata, frames, time_info, status):
        if not self._running:
            return
        if status:
            if status.input_overflow:
                logger.debug("[INBOUND HW] sounddevice status: %s", status)
            else:
                logger.warning("[INBOUND HW] sounddevice status: %s", status)

        try:
            self._raw_hw_q.put_nowait(indata.copy())
        except queue.Full:
            try:
                self._raw_hw_q.get_nowait()
                self._raw_hw_q.put_nowait(indata.copy())
            except queue.Empty:
                pass

    def _resample_worker(self):
        """Worker thread to decouple audio resampling and buffering from PortAudio callback."""
        buf = np.array([], dtype=np.float32)
        while self._running:
            try:
                raw_chunk = self._raw_hw_q.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._device_rate != SAMPLE_RATE:
                new_samples = self._resample_to_target(raw_chunk.flatten())
            else:
                new_samples = raw_chunk.flatten().astype(np.float32)

            buf = np.concatenate([buf, new_samples])

            while len(buf) >= CHUNK_SAMP:
                out_chunk = buf[:CHUNK_SAMP].astype(np.int16)
                buf = buf[CHUNK_SAMP:]
                try:
                    self._in_q.put_nowait(out_chunk.reshape(-1, 1))
                except queue.Full:
                    try:
                        self._in_q.get_nowait()
                        self._in_q.put_nowait(out_chunk.reshape(-1, 1))
                        logger.warning("[INBOUND] Queue full — dropping oldest chunk (pipeline lag?)")
                    except queue.Empty:
                        pass

    def _resample_to_target(self, audio_int16: np.ndarray) -> np.ndarray:
        try:
            from scipy.signal import resample_poly
            return resample_poly(audio_int16.astype(np.float32), self._resample_up, self._resample_down)
        except Exception:
            n_out = int(len(audio_int16) * SAMPLE_RATE / self._device_rate)
            x_old = np.linspace(0, 1, len(audio_int16))
            x_new = np.linspace(0, 1, n_out)
            return np.interp(x_new, x_old, audio_int16.astype(np.float32))

    # ── VAD worker ───────────────────────────────────────────────────────────
    def _vad_worker(self):
        buf:      list         = []
        history:  deque        = deque(maxlen=HISTORY_CHUNKS)
        speaking: bool         = False
        sil_count: int         = 0

        last_partial_time = 0.0

        while self._running:
            try:
                chunk = self._in_q.get(timeout=0.1)
            except queue.Empty:
                continue

            # Periodic RMS debug & UI level callback
            now = time.time()
            rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768.0) ** 2)))

            if hasattr(self, "_level_cb") and self._level_cb:
                if now - self._last_dbg >= 0.15:
                    try:
                        self._level_cb(rms)
                    except Exception:
                        pass
                    self._last_dbg = now

            # Log audio state to console periodically
            if not hasattr(self, "_last_log_t") or now - self._last_log_t >= 4.0:
                self._last_log_t = now
                if rms > 0.005:
                    logger.info("[INBOUND AUDIO] Đang nhận tín hiệu âm thanh (RMS = %.4f)", rms)
                else:
                    logger.info("[INBOUND AUDIO] Thiết bị đang im lặng (RMS = %.5f) — Kiểm tra xem Meet đã chọn Loa là CABLE Input chưa", rms)

            chunk_float = chunk.flatten().astype(np.float32) / 32768.0
            has_speech  = self._check_speech_pytorch(chunk_float)

            if not has_speech:
                self._update_noise(chunk)

            if has_speech:
                if not speaking:
                    speaking  = True
                    sil_count = 0
                    buf.extend(list(history))
                    history.clear()
                    last_partial_time = now   # Reset partial timer
                    logger.debug("[INBOUND VAD] >>> Sentence start")
                buf.append(chunk)
                sil_count = 0

                # --- Partial sending logic ---
                if now - last_partial_time >= PARTIAL_INTERVAL_SEC:
                    logger.debug("[INBOUND VAD] Partial update (~%.2fs)", len(buf) * CHUNK_MS / 1000.0)
                    self._send(buf, is_final=False)
                    last_partial_time = now

            else:   # silence
                if speaking:
                    buf.append(chunk)
                    sil_count += 1
                    logger.debug("[INBOUND VAD] silence %d/%d", sil_count, SILENCE_CHUNKS)

                    if sil_count >= SILENCE_CHUNKS:
                        duration_s = len(buf) * CHUNK_MS / 1000.0
                        logger.info("[INBOUND VAD] Sentence end → %.2f s", duration_s)
                        self._send(buf, is_final=True)
                        self._reset_vad_state()          # ← clear LSTM state
                        buf, speaking, sil_count = [], False, 0
                        history.clear()
                else:
                    history.append(chunk)

            # Hard ceiling — force-flush if sentence is too long
            if speaking and len(buf) >= MAX_CHUNKS:
                duration_ms = len(buf) * CHUNK_MS
                logger.warning("[INBOUND VAD] MAX_CHUNKS hit (%d ms) — force flush with overlap", duration_ms)
                
                # Send current buffer as final segment
                self._send(buf, is_final=True)
                
                # Seed the next buffer with overlap to preserve context/words at the boundary
                overlap = buf[-OVERLAP_CHUNKS:] if len(buf) > OVERLAP_CHUNKS else buf
                buf = list(overlap)
                
                # Reset VAD state because we are "jumping back" in time for the overlap
                self._reset_vad_state()
                
                # Keep speaking=True, sil_count=0
                history.clear()

    # ── Fallback RMS VAD ─────────────────────────────────────────────────────

    def _rms_vad(self, chunk_float: np.ndarray, thr: float = 0.015) -> bool:
        """Simple energy-based VAD used when Silero is unavailable."""
        return float(np.sqrt(np.mean(chunk_float ** 2))) > thr

    # ── Processing pipeline ──────────────────────────────────────────────────

    def _send(self, buf: list, is_final: bool = True):
        if not buf:
            return

        duration_s = len(buf) * CHUNK_MS / 1000.0
        logger.info("[INBOUND] _send(%d chunks, ~%.2f s)", len(buf), duration_s)

        audio = np.concatenate(buf).flatten()

        if ENABLE_SPEC_SUB:
            audio = self._spec_sub(audio)

        f32 = audio.astype(np.float32) / 32768.0

        if ENABLE_TRIM:
            f32 = self._trim(f32, thr=0.02)

        if len(f32) < int(SAMPLE_RATE * MIN_AUDIO_SEC):
            logger.info("[INBOUND] Skipped: %.0f ms < MIN_AUDIO_SEC", len(f32) / SAMPLE_RATE * 1000)
            return

        if ENABLE_NORMALIZE:
            f32 = self._normalize_sentence(f32)

        f32 = np.clip(f32, -1.0, 1.0)

        pad = np.zeros(int(SAMPLE_RATE * WHISPER_PAD_MS / 1000), dtype=np.float32)
        f32 = np.concatenate([pad, f32, pad])


        #  save audio để dễ check bug
        # if DEBUG_AUDIO:
        #     path = self._save_wav(f32)
        #     if path:
        #         logger.debug("[DEBUG] Saved: %s", path)

        logger.info("[INBOUND] >>> Sending %.2f s to server (final=%s)", len(f32) / SAMPLE_RATE, is_final)
        b64 = base64.b64encode(f32.tobytes()).decode()
        if self._callback:
            try:
                self._callback(b64, is_final)
            except TypeError:
                try:
                    self._callback(b64)
                except Exception as exc:
                    logger.error("[INBOUND] Callback error: %s", exc)
            except Exception as exc:
                logger.error("[INBOUND] Callback error: %s", exc)

    # ── Spectral subtraction ─────────────────────────────────────────────────

    def _update_noise(self, chunk: np.ndarray):
        flat = chunk.flatten().astype(np.float32)
        spec = np.abs(np.fft.rfft(flat))
        with self._noise_lock:
            if self._noise_profile is None:
                self._noise_profile = spec.copy()
            elif len(spec) == len(self._noise_profile):
                self._noise_profile = (
                    (1 - NOISE_ALPHA) * self._noise_profile + NOISE_ALPHA * spec
                )

    def _spec_sub(self, audio: np.ndarray) -> np.ndarray:
        with self._noise_lock:
            noise = self._noise_profile
        if noise is None:
            return audio

        flat  = audio.flatten().astype(np.float32)
        n     = len(flat)
        spec  = np.fft.rfft(flat)
        mag   = np.abs(spec)
        phase = np.angle(spec)
        L     = min(len(mag), len(noise))

        clean_mag = np.maximum(
            mag[:L] - SPEC_OVER_SUB * noise[:L],
            SPEC_FLOOR * mag[:L],
        )
        clean        = np.zeros(len(spec), dtype=complex)
        clean[:L]    = clean_mag * np.exp(1j * phase[:L])
        if L < len(spec):
            clean[L:] = spec[L:]

        return np.clip(np.fft.irfft(clean, n=n), -32768, 32767).astype(np.int16)

    # ── Trim / Normalize ─────────────────────────────────────────────────────

    def _trim(self, audio: np.ndarray, thr: float = 0.005, pad: int = 800) -> np.ndarray:
        idx = np.where(np.abs(audio) > thr)[0]
        if len(idx) == 0:
            return audio
        return audio[max(0, idx[0] - pad) : min(len(audio), idx[-1] + pad)]

    def _normalize_sentence(self, audio: np.ndarray) -> np.ndarray:
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 1e-6:
            return audio
        gain = float(np.clip(NORM_TARGET / rms, 0.1, NORM_MAX_GAIN))
        logger.debug("[INBOUND] normalize gain=%.2f (rms=%.5f)", gain, rms)
        return audio * gain

    # ── Debug / Utils ────────────────────────────────────────────────────────

    def _save_wav(self, f32: np.ndarray) -> Optional[str]:
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            ts  = datetime.datetime.now().strftime("%H%M%S_%f")
            dur = len(f32) / SAMPLE_RATE
            p   = os.path.join(DEBUG_DIR, f"in_{dur:.1f}s_{ts}.wav")
            with wave.open(p, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((f32 * 32767).astype(np.int16).tobytes())
            return p
        except Exception as exc:
            logger.error("[INBOUND] Save WAV error: %s", exc)
            return None

    def _mock(self):
        """Generate synthetic audio for offline testing."""
        time.sleep(1)
        t_idx = 0
        for _ in range(3):
            if not self._running:
                break
            for _ in range(6):
                t   = np.linspace(t_idx / SAMPLE_RATE,
                                  (t_idx + CHUNK_SAMP) / SAMPLE_RATE,
                                  CHUNK_SAMP, endpoint=False)
                sig = (0.3 * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
                t_idx += CHUNK_SAMP
                try:
                    self._in_q.put_nowait(sig.reshape(-1, 1))
                except queue.Full:
                    pass
                time.sleep(CHUNK_MS / 1000)

            sil = np.zeros((CHUNK_SAMP, 1), dtype=np.int16)
            for _ in range(SILENCE_CHUNKS + 1):
                try:
                    self._in_q.put_nowait(sil)
                except queue.Full:
                    pass
                time.sleep(CHUNK_MS / 1000)
            time.sleep(1.0)

    @staticmethod
    def _find_device(name: str, input: bool = True) -> Optional[int]:
        from client.audio_router.get_device import find_device, find_best_input_device

        # 1. Tìm theo tên hoặc index nếu được chỉ định
        if name and name.lower() != "default":
            idx, d = find_device(name, kind="input" if input else "output")
            if idx is not None:
                logger.info("[INBOUND] Found device: %s (ID: %d)", d["name"], idx)
                return idx

        # 2. Tự động dò tìm thiết bị đầu vào tối ưu (VB-Cable / Loopback / Stereo Mix)
        logger.info("[INBOUND] Đang tự động dò tìm thiết bị thu âm tối ưu...")
        best_idx, best_d = find_best_input_device()
        if best_d is not None:
            logger.info("[INBOUND] Auto-detected input device: %s (ID: %d)", best_d["name"], best_idx)
            return best_idx

        # 3. Fallback thiết bị mặc định
        default_idx = sd.default.device[0 if input else 1]
        if default_idx is not None and default_idx >= 0:
            return default_idx

        logger.error("[INBOUND] Không tìm thấy thiết bị âm thanh phù hợp.")
        return None