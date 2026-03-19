"""
client/audio_router/audio_manager.py
VB-Audio Virtual Cable routing.

Inbound:  Virtual Speaker (Teams Audio Out) → capture PCM → send to server
Outbound: Real Microphone → capture PCM → send to server
Playback: Receive TTS WAV from server → play to Real Headphone

Requires: pip install sounddevice
Hardware: VB-Audio Virtual Cable installed on Windows
          https://vb-audio.com/Cable/
"""
import base64
import io
import logging
import os
import threading
import wave
from queue import Queue, Empty
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger("paraline.audio")

SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
CHUNK_MS    = int(os.getenv("AUDIO_CHUNK_MS",    "500"))
CHUNK_SAMP  = SAMPLE_RATE * CHUNK_MS // 1000
VIRTUAL_SPK = os.getenv("VIRTUAL_SPEAKER_NAME",  "CABLE Output")


class AudioManager:
    def __init__(self):
        self._running        = False
        self._inbound_cb:  Optional[Callable] = None
        self._outbound_cb: Optional[Callable] = None
        self._playback_q   = Queue(maxsize=30)
        self._playback_thr: Optional[threading.Thread] = None

        # Buffers for VAD accumulation
        self._in_buf = []
        self._in_hist = []
        self._in_silence = 0

        self._out_buf = []
        self._out_hist = []
        self._out_silence = 0

    # ─────────────────────────────────────────────
    # Start / Stop
    # ─────────────────────────────────────────────

    def start(self, inbound_cb: Callable, outbound_cb: Callable):
        """
        inbound_cb(audio_b64: str)  — called with each 500ms chunk from Virtual Speaker
        outbound_cb(audio_b64: str) — called with each 500ms chunk from Real Mic
        """
        self._inbound_cb  = inbound_cb
        self._outbound_cb = outbound_cb
        self._running     = True

        virtual_spk_idx = self._find_device(VIRTUAL_SPK, input=True)
        real_mic_idx    = sd.default.device[0]

        logger.info(f"Inbound  device: [{virtual_spk_idx}] {VIRTUAL_SPK}")
        logger.info(f"Outbound device: [{real_mic_idx}] (default mic)")

        # ── Inbound stream ────────────────────────────────────
        if virtual_spk_idx >= 0:
            self._inbound_stream = sd.InputStream(
                device=virtual_spk_idx,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SAMP,
                callback=self._inbound_audio_cb,
            )
            self._inbound_stream.start()
        else:
            logger.warning("⚠️ No Virtual Cable found. Mocking inbound audio from 'mock_en.wav' for testing!")
            self._mock_inbound_thr = threading.Thread(target=self._mock_inbound_worker, daemon=True)
            self._mock_inbound_thr.start()

        # ── Outbound stream ───────────────────────────────────
        if real_mic_idx is not None and real_mic_idx >= 0:
            self._outbound_stream = sd.InputStream(
                device=real_mic_idx,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SAMP,
                callback=self._outbound_audio_cb,
            )
            self._outbound_stream.start()
        else:
            logger.error("⚠️ No valid default mic! Outbound audio disabled.")

        # ── Playback thread ───────────────────────────────────
        self._playback_thr = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thr.start()

        logger.info("✅ Audio streams started")

    def stop(self):
        self._running = False
        if hasattr(self, "_inbound_stream"):
            self._inbound_stream.stop()
        if hasattr(self, "_outbound_stream"):
            self._outbound_stream.stop()
        logger.info("Audio streams stopped")

    def play_tts(self, audio_b64: str):
        """Queue TTS audio for playback on Real Headphone."""
        try:
            self._playback_q.put_nowait(audio_b64)
        except Exception:
            logger.debug("Playback queue full, dropping TTS chunk")

    def _mock_inbound_worker(self):
        """
        Generates synthetic (non-silent) sine wave audio chunks and feeds them
        into the inbound VAD accumulator exactly as if a Virtual Cable were present.
        Whisper receives real PCM data; MOCK_TRANSCRIPTION_TEXT in the server env
        makes it bypass ASR and return a predetermined text for translation.
        """
        import time

        MOCK_TEXTS = [
            "Hello everyone, today we will discuss the project timeline.",
            "The development team has finished the first phase.",
            "We need to review the requirements before the next sprint.",
            "Please share your feedback on the current design proposal.",
            "The meeting will wrap up with a summary of action items.",
        ]

        logger.info("🎵 Starting sine-wave mock inbound audio...")
        time.sleep(2)  # Brief delay so UI is ready

        chunk = SAMPLE_RATE // 2  # 500ms per chunk
        t_idx = 0

        for phrase in MOCK_TEXTS:
            if not self._running:
                break

            # Generate a simple 440Hz sine wave — non-silent so VAD passes it
            t = np.linspace(t_idx / SAMPLE_RATE, (t_idx + chunk) / SAMPLE_RATE, chunk, endpoint=False)
            sine = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(-1, 1)
            t_idx += chunk

            logger.info(f"[mock] sending phrase: {phrase[:40]}...")

            # Feed through exactly the same VAD accumulator as real audio
            # We send 6 speech chunks then 2 silence chunks to trigger flush
            for _ in range(6):
                self._inbound_audio_cb(sine, len(sine), None, None)
                time.sleep(0.5)

            # Two silence chunks → triggers flush in VAD accumulator
            silence = np.zeros((chunk, 1), dtype=np.float32)
            for _ in range(2):
                self._inbound_audio_cb(silence, len(silence), None, None)
                time.sleep(0.5)

            # Pause between sentences
            time.sleep(1.5)

        logger.info("🏁 Mock inbound audio finished.")



    def list_devices(self):
        """Print all audio devices — helper for initial setup."""
        for i, d in enumerate(sd.query_devices()):
            print(f"[{i:2d}] {'IN' if d['max_input_channels'] > 0 else '  '} "
                  f"{'OUT' if d['max_output_channels'] > 0 else '   '} {d['name']}")

    # ─────────────────────────────────────────────
    # Stream Callbacks (called from sounddevice thread)
    # ─────────────────────────────────────────────

    def _inbound_audio_cb(self, indata, frames, time_info, status):
        if not self._running:
            return
        rms = np.sqrt(np.mean(indata**2))
        is_silence = rms < 0.0005   # VAD: silence threshold (lowered for Virtual Cable)
        
        if is_silence:
            self._in_silence += 1
            if len(self._in_buf) > 0 and self._in_silence >= 1:
                full = np.concatenate(self._in_buf)
                self._inbound_cb(base64.b64encode(full.tobytes()).decode())
                self._in_buf.clear()
            else:
                self._in_hist = [indata.copy()]
        else:
            self._in_silence = 0
            if not self._in_buf and self._in_hist:
                self._in_buf.extend(self._in_hist)
            self._in_buf.append(indata.copy())
            if len(self._in_buf) >= 10:  # max 5 seconds
                full = np.concatenate(self._in_buf)
                self._inbound_cb(base64.b64encode(full.tobytes()).decode())
                self._in_buf.clear()
                self._in_hist.clear()

    def _outbound_audio_cb(self, indata, frames, time_info, status):
        if not self._running:
            return
        rms = np.sqrt(np.mean(indata**2))
        is_silence = rms < 0.0015   # VAD: silence threshold for Real Mic
        
        if is_silence:
            self._out_silence += 1
            if len(self._out_buf) > 0 and self._out_silence >= 1:
                full = np.concatenate(self._out_buf)
                self._outbound_cb(base64.b64encode(full.tobytes()).decode())
                self._out_buf.clear()
            else:
                self._out_hist = [indata.copy()]
        else:
            self._out_silence = 0
            if not self._out_buf and self._out_hist:
                self._out_buf.extend(self._out_hist)
            self._out_buf.append(indata.copy())
            if len(self._out_buf) >= 10:  # max 5 seconds
                full = np.concatenate(self._out_buf)
                self._outbound_cb(base64.b64encode(full.tobytes()).decode())
                self._out_buf.clear()
                self._out_hist.clear()

    # ─────────────────────────────────────────────
    # Playback
    # ─────────────────────────────────────────────

    def _playback_worker(self):
        """Thread: play TTS WAV audio to Real Headphone."""
        out_device = sd.default.device[1]
        while self._running:
            try:
                audio_b64 = self._playback_q.get(timeout=0.1)
                wav_bytes = base64.b64decode(audio_b64)
                with wave.open(io.BytesIO(wav_bytes)) as wf:
                    pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                    audio_f32 = pcm.astype(np.float32) / 32768.0
                    sr = wf.getframerate()
                sd.play(audio_f32, samplerate=sr, device=out_device, blocking=True)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Playback error: {e}")

    @staticmethod
    def _find_device(name: str, input: bool = True) -> int:
        key = "max_input_channels" if input else "max_output_channels"
        for i, d in enumerate(sd.query_devices()):
            if name.lower() in d["name"].lower() and d[key] > 0:
                return i
        logger.warning(f"Device '{name}' not found, using default")
        return sd.default.device[0] if input else sd.default.device[1]
