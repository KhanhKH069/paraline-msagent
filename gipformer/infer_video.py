#!/usr/bin/env python3
"""
Gipformer Video Inference - Vietnamese ASR from Video Files
Trích xuất âm thanh từ video rồi nhận diện giọng nói tiếng Việt.

Yêu cầu: ffmpeg phải được cài đặt và có trong PATH
    - Windows: https://ffmpeg.org/download.html (hoặc: winget install ffmpeg)
    - Ubuntu: sudo apt install ffmpeg
    - macOS: brew install ffmpeg

Cài thêm thư viện Python:
    pip install moviepy soundfile sherpa-onnx huggingface_hub numpy

Usage:
    # Nhận diện 1 video (offline - batch):
    python infer_video.py --video data/sample.mp4

    # Nhận diện nhiều video cùng lúc:
    python infer_video.py --video v1.mp4 v2.mp4 v3.mkv

    # Dùng model int8 (nhanh hơn, nhẹ hơn):
    python infer_video.py --video data/sample.mp4 --quantize int8

    # Chia video thành từng đoạn nhỏ (realtime simulation, mỗi chunk N giây):
    python infer_video.py --video data/sample.mp4 --realtime --chunk-size 5

    # Chỉ trích xuất âm thanh ra file WAV, không nhận diện:
    python infer_video.py --video data/sample.mp4 --extract-only
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

try:
    from translator import print_translations, is_available as translator_available
except ImportError:
    def print_translations(text, indent="   "):  # type: ignore[misc]
        print(f"{indent}⚠️  Không tìm thấy translator.py hoặc deep-translator chưa cài.")
    def translator_available() -> bool:  # type: ignore[misc]
        return False

try:
    import sherpa_onnx
except ImportError:
    print("Lỗi: Chưa cài đặt sherpa-onnx.")
    print("Vui lòng chạy: pip install sherpa-onnx")
    sys.exit(1)

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("Lỗi: Chưa cài đặt huggingface_hub.")
    print("Vui lòng chạy: pip install huggingface_hub")
    sys.exit(1)

REPO_ID = "g-group-ai-lab/gipformer-65M-rnnt"
SAMPLE_RATE = 16000
FEATURE_DIM = 80

ONNX_FILES = {
    "fp32": {
        "encoder": "encoder-epoch-35-avg-6.onnx",
        "decoder": "decoder-epoch-35-avg-6.onnx",
        "joiner":  "joiner-epoch-35-avg-6.onnx",
    },
    "int8": {
        "encoder": "encoder-epoch-35-avg-6.int8.onnx",
        "decoder": "decoder-epoch-35-avg-6.int8.onnx",
        "joiner":  "joiner-epoch-35-avg-6.int8.onnx",
    },
}

# Các định dạng video phổ biến được hỗ trợ
SUPPORTED_VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".flv", ".wmv", ".m4v", ".ts", ".mpeg", ".mpg",
}


# ──────────────────────────────────────────────────────────────
# Kiểm tra ffmpeg
# ──────────────────────────────────────────────────────────────

def check_ffmpeg() -> str:
    """Kiểm tra ffmpeg có trong PATH không. Trả về đường dẫn hoặc thoát."""
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

    print("=" * 60)
    print("❌ Không tìm thấy ffmpeg trong PATH!")
    print()
    print("Cài đặt ffmpeg:")
    print("  Windows : winget install ffmpeg")
    print("            hoặc tải tại https://ffmpeg.org/download.html")
    print("  Ubuntu  : sudo apt install ffmpeg")
    print("  macOS   : brew install ffmpeg")
    print("=" * 60)
    sys.exit(1)


# ──────────────────────────────────────────────────────────────
# Trích xuất âm thanh
# ──────────────────────────────────────────────────────────────

def extract_audio_ffmpeg(
    video_path: str,
    output_wav: str,
    ffmpeg_cmd: str = "ffmpeg",
) -> None:
    """
    Dùng ffmpeg để trích xuất audio từ video, chuyển sang WAV 16kHz mono float32.

    Args:
        video_path : Đường dẫn file video đầu vào.
        output_wav : Đường dẫn file WAV đầu ra.
        ffmpeg_cmd : Lệnh ffmpeg (mặc định "ffmpeg").
    """
    cmd = [
        ffmpeg_cmd,
        "-y",                    # Ghi đè nếu tồn tại
        "-i", video_path,        # Input
        "-vn",                   # Bỏ track video
        "-acodec", "pcm_f32le",  # Mã hóa WAV float32 little-endian
        "-ar", str(SAMPLE_RATE), # Resample → 16kHz
        "-ac", "1",              # Mono
        output_wav,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg thất bại:\n{err}")


def load_audio_from_video(video_path: str, ffmpeg_cmd: str = "ffmpeg") -> np.ndarray:
    """
    Extract audio từ video, trả về numpy array float32 (16kHz mono).

    Args:
        video_path: Đường dẫn file video.
        ffmpeg_cmd: Lệnh ffmpeg.

    Returns:
        numpy array shape (N,) float32 ở 16000 Hz.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        extract_audio_ffmpeg(video_path, tmp_path, ffmpeg_cmd)
        samples, sr = sf.read(tmp_path, dtype="float32")
        if samples.ndim > 1:          # stereo → mono (dự phòng)
            samples = samples.mean(axis=1)
        if sr != SAMPLE_RATE:
            raise RuntimeError(
                f"Sample rate không đúng: nhận được {sr} Hz, cần {SAMPLE_RATE} Hz."
            )
        return samples
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────
# Model (download + khởi tạo)
# ──────────────────────────────────────────────────────────────

def download_model(quantize: str = "fp32") -> dict:
    """Tải model ONNX từ HuggingFace Hub."""
    files = ONNX_FILES[quantize]
    print(f"⏬ Kiểm tra / tải model ({quantize}) từ {REPO_ID}...")

    paths: dict = {}
    for key, filename in files.items():
        paths[key] = hf_hub_download(repo_id=REPO_ID, filename=filename)

    paths["tokens"] = hf_hub_download(repo_id=REPO_ID, filename="tokens.txt")
    print("✅ Model sẵn sàng.\n")
    return paths


def create_recognizer(
    model_paths: dict,
    num_threads: int = 4,
    decoding_method: str = "greedy_search",
) -> sherpa_onnx.OfflineRecognizer:
    """Tạo OfflineRecognizer từ model paths."""
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


# ──────────────────────────────────────────────────────────────
# Nhận diện
# ──────────────────────────────────────────────────────────────

def transcribe_samples(
    recognizer: sherpa_onnx.OfflineRecognizer,
    samples: np.ndarray,
) -> str:
    """Chuyển numpy array sang text."""
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_streams([stream])
    return stream.result.text.strip()


def transcribe_realtime(
    recognizer: sherpa_onnx.OfflineRecognizer,
    samples: np.ndarray,
    chunk_size: int = 5,
) -> str:
    """
    Giả lập nhận diện realtime bằng cách chia audio thành các chunk nhỏ.

    Args:
        recognizer : OfflineRecognizer đã khởi tạo.
        samples    : Toàn bộ audio (float32, 16kHz).
        chunk_size : Độ dài mỗi chunk (giây).

    Returns:
        Chuỗi transcript đầy đủ.
    """
    chunk_samples = chunk_size * SAMPLE_RATE
    total_samples = len(samples)
    chunks = [
        samples[i : i + chunk_samples]
        for i in range(0, total_samples, chunk_samples)
    ]
    total_chunks = len(chunks)
    all_texts: list[str] = []

    print(f"\n📡 Realtime simulation | Chunk: {chunk_size}s | Tổng: {total_chunks} chunks")
    print("-" * 55)

    total_audio_processed = 0.0
    total_infer_time = 0.0

    for idx, chunk in enumerate(chunks, 1):
        audio_duration = len(chunk) / SAMPLE_RATE
        total_audio_processed += audio_duration

        t0 = time.time()
        text = transcribe_samples(recognizer, chunk)
        elapsed = time.time() - t0
        total_infer_time += elapsed

        rtf = elapsed / audio_duration if audio_duration > 0 else 0
        status = "🟢" if rtf < 1.0 else "🔴"

        print(
            f"  [{idx:>3}/{total_chunks}] {status} RTF={rtf:.3f} | "
            f"⏱ {elapsed:.2f}s / {audio_duration:.2f}s | 📝 {text or '(im lặng)'}"
        )
        if text:
            all_texts.append(text)

    avg_rtf = total_infer_time / total_audio_processed if total_audio_processed > 0 else 0
    print("-" * 55)
    print(f"  Tổng audio: {total_audio_processed:.1f}s | "
          f"Thời gian xử lý: {total_infer_time:.2f}s | RTF trung bình: {avg_rtf:.3f}")

    return " ".join(all_texts)


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Gipformer Video Inference - Nhận diện giọng nói tiếng Việt từ video",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ví dụ:\n"
            "  python infer_video.py --video data/sample.mp4\n"
            "  python infer_video.py --video v1.mp4 v2.mkv --quantize int8\n"
            "  python infer_video.py --video sample.mp4 --realtime --chunk-size 5\n"
            "  python infer_video.py --video sample.mp4 --extract-only\n"
        ),
    )

    parser.add_argument(
        "--video",
        nargs="+",
        required=True,
        metavar="FILE",
        help="Đường dẫn tới file(s) video cần nhận diện",
    )
    parser.add_argument(
        "--quantize",
        choices=["fp32", "int8"],
        default="fp32",
        help="Độ chính xác model: fp32 (mặc định) hoặc int8 (nhanh hơn)",
    )
    parser.add_argument(
        "--num-threads",
        type=int,
        default=4,
        help="Số luồng CPU (mặc định: 4)",
    )
    parser.add_argument(
        "--decoding-method",
        choices=["greedy_search", "modified_beam_search"],
        default="greedy_search",
        help="Phương pháp giải mã (mặc định: greedy_search)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Giả lập nhận diện realtime từng chunk nhỏ",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5,
        metavar="SECONDS",
        help="Độ dài mỗi chunk khi dùng --realtime (mặc định: 5 giây)",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Chỉ trích xuất audio ra WAV, không nhận diện",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Thư mục lưu file WAV đã trích xuất (mặc định: cùng thư mục video)",
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="Dịch kết quả tiếng Việt sang tiếng Anh và tiếng Nhật (cần: pip install deep-translator)",
    )

    args = parser.parse_args()

    # 1. Kiểm tra ffmpeg
    ffmpeg_cmd = check_ffmpeg()
    print("✅ ffmpeg: OK\n")

    # 2. Validate video files
    valid_videos: list[str] = []
    for vp in args.video:
        p = Path(vp)
        if not p.exists():
            print(f"⚠️  Không tìm thấy file: {vp}")
            continue
        if p.suffix.lower() not in SUPPORTED_VIDEO_EXTS:
            print(f"⚠️  Định dạng không được hỗ trợ ({p.suffix}): {vp}")
            continue
        valid_videos.append(str(p))

    if not valid_videos:
        print("❌ Không có video hợp lệ nào để xử lý.")
        sys.exit(1)

    # 3. Tải model (bỏ qua nếu chỉ extract)
    recognizer = None
    if not args.extract_only:
        model_paths = download_model(args.quantize)
        recognizer = create_recognizer(
            model_paths,
            num_threads=args.num_threads,
            decoding_method=args.decoding_method,
        )

    # 4. Xử lý từng video
    print("=" * 60)
    for video_path in valid_videos:
        vp = Path(video_path)
        print(f"\n🎬 Video: {vp.name}")
        print(f"   Đường dẫn: {video_path}")

        # ── Xác định đường dẫn WAV output ──
        out_dir = Path(args.output_dir) if args.output_dir else vp.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / (vp.stem + "_audio.wav")

        # ── Trích xuất âm thanh ──
        print(f"   🔊 Đang trích xuất âm thanh → {wav_path.name} ...")
        t_extract_start = time.time()
        try:
            extract_audio_ffmpeg(video_path, str(wav_path), ffmpeg_cmd)
        except RuntimeError as exc:
            print(f"   ❌ Lỗi trích xuất: {exc}")
            continue
        t_extract = time.time() - t_extract_start

        audio_info = sf.info(str(wav_path))
        print(f"   ✅ Trích xuất xong | {audio_info.duration:.1f}s | {t_extract:.2f}s")
        print(f"   💾 Lưu tại: {wav_path}")

        if args.extract_only:
            continue

        # ── Đọc audio ──
        samples, _ = sf.read(str(wav_path), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        # ── Nhận diện ──
        if args.realtime:
            transcript = transcribe_realtime(recognizer, samples, args.chunk_size)
        else:
            print("   🤖 Đang nhận diện (offline batch)...")
            t0 = time.time()
            transcript = transcribe_samples(recognizer, samples)
            elapsed = time.time() - t0
            rtf = elapsed / audio_info.duration if audio_info.duration > 0 else 0
            print(f"   ⏱  Xử lý: {elapsed:.2f}s | RTF: {rtf:.3f}")

        print(f"\n   📝 KẾT QUẢ:")
        print(f"   🇻🇳 VI: {transcript or '(Không nhận diện được)'}")
        if args.translate and transcript:
            print_translations(transcript, indent="   ")
        print("=" * 60)


if __name__ == "__main__":
    main()
