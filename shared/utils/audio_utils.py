"""
shared/utils/audio_utils.py
Audio encoding/decoding helpers dùng chung client ↔ server.
"""
import base64
import io
import struct
import wave

import numpy as np


def pcm_float32_to_b64(audio_np: np.ndarray) -> str:
    """Encode numpy float32 PCM array → base64 string."""
    return base64.b64encode(audio_np.astype(np.float32).tobytes()).decode("utf-8")


def b64_to_pcm_float32(b64: str) -> np.ndarray:
    """Decode base64 string → numpy float32 PCM array."""
    return np.frombuffer(base64.b64decode(b64), dtype=np.float32)


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int = 22050, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw PCM bytes in a WAV container."""
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate,
        sample_rate * channels * bits // 8,
        channels * bits // 8, bits,
        b"data", data_size,
    )
    return header + pcm


def wav_b64_to_float32(wav_b64: str) -> tuple[np.ndarray, int]:
    """Decode base64 WAV → (float32 numpy, sample_rate)."""
    wav_bytes = base64.b64decode(wav_b64)
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        sr  = wf.getframerate()
    return pcm.astype(np.float32) / 32768.0, sr


def detect_silence(audio_np: np.ndarray, threshold: float = 0.005) -> bool:
    """Simple RMS-based silence detection."""
    rms = float(np.sqrt(np.mean(audio_np ** 2)))
    return rms < threshold
