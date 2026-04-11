"""
services/asr-service/core/recognizer.py

Core Vietnamese ASR engine using Gipformer (sherpa-onnx).
Wraps sherpa-onnx OfflineRecognizer for use as a shared singleton.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("paraline.asr.recognizer")

REPO_ID = "g-group-ai-lab/gipformer-65M-rnnt"
SAMPLE_RATE = 16_000
FEATURE_DIM = 80

ONNX_FILES: dict[str, dict[str, str]] = {
    "fp32": {
        "encoder": "encoder-epoch-35-avg-6.onnx",
        "decoder": "decoder-epoch-35-avg-6.onnx",
        "joiner": "joiner-epoch-35-avg-6.onnx",
    },
    "int8": {
        "encoder": "encoder-epoch-35-avg-6.int8.onnx",
        "decoder": "decoder-epoch-35-avg-6.int8.onnx",
        "joiner": "joiner-epoch-35-avg-6.int8.onnx",
    },
}


def download_model(quantize: str = "fp32") -> dict[str, str]:
    """Download Gipformer ONNX model files from HuggingFace Hub.

    Args:
        quantize: "fp32" (full precision) or "int8" (quantized, faster).

    Returns:
        Dict with local file paths for encoder, decoder, joiner, tokens.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required. Install it with: pip install huggingface_hub"
        ) from exc

    files = ONNX_FILES[quantize]
    logger.info("Downloading Gipformer model (%s) from %s ...", quantize, REPO_ID)

    paths: dict[str, str] = {}
    for key, filename in files.items():
        paths[key] = hf_hub_download(repo_id=REPO_ID, filename=filename)

    paths["tokens"] = hf_hub_download(repo_id=REPO_ID, filename="tokens.txt")
    logger.info("Gipformer model ready.")
    return paths


def create_recognizer(
    model_paths: dict[str, str],
    num_threads: int = 4,
    decoding_method: str = "greedy_search",
):
    """Instantiate a sherpa_onnx OfflineRecognizer from model paths.

    Args:
        model_paths:     Dict returned by :func:`download_model`.
        num_threads:     CPU thread count.
        decoding_method: "greedy_search" or "modified_beam_search".

    Returns:
        sherpa_onnx.OfflineRecognizer
    """
    try:
        import sherpa_onnx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "sherpa-onnx is required. Install it with: pip install sherpa-onnx"
        ) from exc

    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=model_paths["encoder"],
        decoder=model_paths["decoder"],
        joiner=model_paths["joiner"],
        tokens=model_paths["tokens"],
        num_threads=num_threads,
        sample_rate=SAMPLE_RATE,
        feature_dim=FEATURE_DIM,
        decoding_method=decoding_method,
    )


def transcribe_samples(recognizer, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe a numpy float32 array to text.

    Args:
        recognizer:  sherpa_onnx.OfflineRecognizer instance.
        samples:     Float32 audio samples.
        sample_rate: Sample rate of the input (will resample if ≠ 16000).

    Returns:
        Recognised Vietnamese text string.
    """
    if sample_rate != SAMPLE_RATE:
        samples = _resample(samples, sample_rate, SAMPLE_RATE)

    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_streams([stream])
    return stream.result.text.strip()


def _resample(samples: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio with scipy (preferred) or numpy linear interpolation."""
    if orig_sr == target_sr:
        return samples

    try:
        from math import gcd

        from scipy.signal import resample_poly  # type: ignore[import-untyped]

        g = gcd(target_sr, orig_sr)
        return resample_poly(samples, target_sr // g, orig_sr // g).astype(np.float32)
    except ImportError:
        pass

    duration = len(samples) / orig_sr
    num_target = int(duration * target_sr)
    old_indices = np.linspace(0, len(samples) - 1, num_target)
    return np.interp(old_indices, np.arange(len(samples)), samples).astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Singleton store — lazily initialised on first request
# ──────────────────────────────────────────────────────────────────────────────

_recognizer = None
_quantize: str = "fp32"
_num_threads: int = 4


def get_recognizer(quantize: str = "fp32", num_threads: int = 4):
    """Return the shared recognizer, initialising it on first call.

    Args:
        quantize:    "fp32" or "int8".
        num_threads: CPU threads for inference.

    Returns:
        sherpa_onnx.OfflineRecognizer
    """
    global _recognizer, _quantize, _num_threads

    if _recognizer is None:
        _quantize = quantize
        _num_threads = num_threads
        model_paths = download_model(quantize)
        _recognizer = create_recognizer(model_paths, num_threads=num_threads)
        logger.info("Gipformer recognizer initialised (quantize=%s, threads=%d)", quantize, num_threads)

    return _recognizer
