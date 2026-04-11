"""
services/asr-service/core/video.py

Audio extraction from video files using ffmpeg.
Adapted from gipformer/infer_video.py.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger("paraline.asr.video")

SAMPLE_RATE = 16_000

SUPPORTED_VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".flv", ".wmv", ".m4v", ".ts", ".mpeg", ".mpg",
}


def check_ffmpeg() -> str:
    """Verify ffmpeg is available in PATH.

    Returns:
        The ffmpeg executable name ("ffmpeg" or "ffmpeg.exe").

    Raises:
        RuntimeError: If ffmpeg is not found.
    """
    for candidate in ("ffmpeg", "ffmpeg.exe"):
        try:
            subprocess.run(
                [candidate, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    raise RuntimeError(
        "ffmpeg not found in PATH. "
        "Install it with: winget install ffmpeg  OR  sudo apt install ffmpeg"
    )


def extract_audio_ffmpeg(
    video_path: str,
    output_wav: str,
    ffmpeg_cmd: str = "ffmpeg",
) -> None:
    """Use ffmpeg to extract audio from a video and write a 16kHz mono WAV.

    Args:
        video_path:  Path to the input video file.
        output_wav:  Path for the output WAV file.
        ffmpeg_cmd:  ffmpeg executable (default "ffmpeg").

    Raises:
        RuntimeError: If ffmpeg exits with a non-zero code.
    """
    cmd = [
        ffmpeg_cmd,
        "-y",                    # overwrite if exists
        "-i", video_path,        # input
        "-vn",                   # drop video track
        "-acodec", "pcm_f32le",  # WAV float32 LE
        "-ar", str(SAMPLE_RATE), # resample → 16kHz
        "-ac", "1",              # mono
        output_wav,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg failed:\n{err}")


def load_audio_from_video(video_path: str, ffmpeg_cmd: str = "ffmpeg") -> np.ndarray:
    """Extract audio from a video file and return a float32 numpy array.

    Args:
        video_path:  Path to the input video file.
        ffmpeg_cmd:  ffmpeg executable name.

    Returns:
        numpy array of shape (N,) at 16000 Hz, float32.

    Raises:
        ValueError:  If video extension is not in SUPPORTED_VIDEO_EXTS.
        RuntimeError: If ffmpeg extraction fails.
    """
    try:
        import soundfile as sf  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "soundfile is required. Install it with: pip install soundfile"
        ) from exc

    ext = Path(video_path).suffix.lower()
    if ext not in SUPPORTED_VIDEO_EXTS:
        raise ValueError(
            f"Unsupported video format '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTS))}"
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        extract_audio_ffmpeg(video_path, tmp_path, ffmpeg_cmd)
        samples, sr = sf.read(tmp_path, dtype="float32")
        if samples.ndim > 1:       # stereo → mono (safety)
            samples = samples.mean(axis=1)
        if sr != SAMPLE_RATE:
            raise RuntimeError(
                f"Unexpected sample rate after extraction: got {sr} Hz, expected {SAMPLE_RATE} Hz."
            )
        logger.debug("Extracted %.1fs of audio from %s", len(samples) / SAMPLE_RATE, video_path)
        return samples
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
