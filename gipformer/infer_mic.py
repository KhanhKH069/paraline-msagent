#!/usr/bin/env python3
"""
Gipformer Microphone / Loopback Inference
Nhận diện giọng nói tiếng Việt từ microphone hoặc thiết bị loopback
(Stereo Mix, VB-Cable, WASAPI loopback…) theo thời gian thực.

Usage:
    # Liệt kê tất cả input devices:
    python infer_mic.py --list-devices

    # Dùng mic mặc định:
    python infer_mic.py

    # Dùng Stereo Mix / VB-Cable (chọn theo index từ --list-devices):
    python infer_mic.py --device 3

    # Dùng model int8 (nhẹ hơn, nhanh hơn):
    python infer_mic.py --device 3 --quantize int8
"""

import argparse
import sys
import time
import queue

import numpy as np

try:
    from translator import print_translations, is_available as translator_available
except ImportError:
    def print_translations(text, indent="   "):  # type: ignore[misc]
        print(f"{indent}⚠️  Không tìm thấy translator.py hoặc deep-translator chưa cài.")
    def translator_available() -> bool:  # type: ignore[misc]
        return False

try:
    import sounddevice as sd
except ImportError:
    print("Lỗi: Chưa cài đặt thư viện sounddevice.")
    print("Vui lòng chạy: pip install sounddevice numpy")
    sys.exit(1)

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
SAMPLE_RATE = 16000  # Sample rate mà model yêu cầu
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


# ──────────────────────────────────────────────────────────────
# Liệt kê / tra cứu thiết bị âm thanh
# ──────────────────────────────────────────────────────────────

def list_input_devices() -> None:
    """In ra danh sách tất cả input devices, highlight các loopback candidate."""
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()

    print("\n" + "=" * 65)
    print("  DANH SÁCH INPUT DEVICES")
    print("=" * 65)
    print(f"  {'IDX':>3}  {'Tên thiết bị':<40}  {'SR mặc định':>11}")
    print("-" * 65)

    loopback_keywords = ("stereo mix", "what u hear", "wave out mix",
                         "vb-cable", "vb cable", "virtual", "loopback",
                         "wasapi", "mix")

    for i, dev in enumerate(devices):
        if dev["max_input_channels"] < 1:
            continue  # Bỏ qua output-only devices

        name: str = dev["name"]
        default_sr = int(dev["default_samplerate"])
        api_name = host_apis[dev["hostapi"]]["name"] if dev["hostapi"] < len(host_apis) else ""

        # Đánh dấu các device có thể là loopback
        is_loopback = any(kw in name.lower() for kw in loopback_keywords)
        tag = "  ⭐ LOOPBACK" if is_loopback else ""

        print(f"  [{i:>3}]  {name:<40}  {default_sr:>8} Hz{tag}")

    print("=" * 65)
    print("\n💡 Gợi ý:")
    print("   - Device có nhãn ⭐ LOOPBACK có thể thu âm hệ thống (YouTube, v.v.)")
    print("   - Nếu không thấy Stereo Mix, hãy bật trong:")
    print("     Control Panel → Sound → Recording → chuột phải → Show Disabled Devices")
    print("   - Hoặc cài VB-Cable: https://vb-audio.com/Cable/\n")


def get_device_info(device_index: int | None) -> dict:
    """Lấy thông tin thiết bị theo index, hoặc default nếu None."""
    if device_index is None:
        return sd.query_devices(kind="input")
    return sd.query_devices(device_index)


def get_device_sample_rate(device_index: int | None) -> int:
    """Trả về sample rate mặc định của thiết bị."""
    info = get_device_info(device_index)
    return int(info["default_samplerate"])


# ──────────────────────────────────────────────────────────────
# Resample (nếu cần)
# ──────────────────────────────────────────────────────────────

def resample(samples: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """
    Resample đơn giản bằng linear interpolation.
    Dùng scipy nếu có (chất lượng tốt hơn), fallback sang numpy.
    """
    if orig_sr == target_sr:
        return samples

    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(target_sr, orig_sr)
        up, down = target_sr // g, orig_sr // g
        return resample_poly(samples, up, down).astype(np.float32)
    except ImportError:
        pass

    # Fallback: numpy linear interpolation
    duration = len(samples) / orig_sr
    num_target = int(duration * target_sr)
    old_indices = np.linspace(0, len(samples) - 1, num_target)
    return np.interp(old_indices, np.arange(len(samples)), samples).astype(np.float32)


# ──────────────────────────────────────────────────────────────
# Model
# ──────────────────────────────────────────────────────────────

def download_model(quantize: str = "fp32") -> dict:
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


def transcribe_array(
    recognizer: sherpa_onnx.OfflineRecognizer,
    samples: np.ndarray,
    sample_rate: int,
) -> str:
    if sample_rate != SAMPLE_RATE:
        samples = resample(samples, sample_rate, SAMPLE_RATE)
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_streams([stream])
    return stream.result.text.strip()


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Gipformer – Nhận diện giọng nói từ Mic / Loopback (Stereo Mix, VB-Cable…)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ví dụ:\n"
            "  python infer_mic.py --list-devices\n"
            "  python infer_mic.py                      # dùng mic mặc định\n"
            "  python infer_mic.py --device 3           # Stereo Mix (index 3)\n"
            "  python infer_mic.py --device 3 --quantize int8\n"
        ),
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Liệt kê tất cả input devices rồi thoát",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Index của thiết bị âm thanh (xem --list-devices). Mặc định: mic hệ thống",
    )
    parser.add_argument(
        "--quantize",
        type=str,
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
        "--translate",
        action="store_true",
        help="Dịch kết quả tiếng Việt sang tiếng Anh và tiếng Nhật (cần: pip install deep-translator)",
    )
    args = parser.parse_args()

    # ── Chế độ liệt kê device ──
    if args.list_devices:
        list_input_devices()
        sys.exit(0)

    # ── Lấy thông tin device được chọn ──
    device_index = args.device
    try:
        dev_info = get_device_info(device_index)
    except Exception as e:
        print(f"❌ Không tìm thấy device index={device_index}: {e}")
        print("   Hãy chạy: python infer_mic.py --list-devices")
        sys.exit(1)

    device_name: str = dev_info["name"]
    device_sr: int = get_device_sample_rate(device_index)
    device_channels: int = min(dev_info["max_input_channels"], 2)  # tối đa stereo

    # Xác định loại device
    loopback_kw = ("stereo mix", "what u hear", "wave out mix",
                   "vb-cable", "vb cable", "virtual", "loopback", "wasapi")
    is_loopback = any(kw in device_name.lower() for kw in loopback_kw)
    device_type = "🔊 LOOPBACK (âm thanh hệ thống)" if is_loopback else "🎤 MICROPHONE"

    print("\n" + "=" * 55)
    print(f"  Thiết bị : {device_name}")
    print(f"  Loại     : {device_type}")
    print(f"  SR       : {device_sr} Hz  →  resample → {SAMPLE_RATE} Hz" if device_sr != SAMPLE_RATE else f"  SR       : {device_sr} Hz")
    print(f"  Channels : {device_channels}")
    print("=" * 55)

    if device_sr != SAMPLE_RATE:
        try:
            from scipy.signal import resample_poly  # noqa: F401
            print("  ✅ scipy phát hiện – sẽ dùng resample_poly (chất lượng cao)")
        except ImportError:
            print("  ⚠️  scipy chưa cài – dùng numpy linear resample (chất lượng thấp hơn)")
            print("      Cài scipy để tốt hơn: pip install scipy")

    # ── Tải model ──
    model_paths = download_model(args.quantize)
    recognizer = create_recognizer(model_paths, num_threads=args.num_threads)

    # ── Vòng lặp thu âm ──
    q: queue.Queue = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        """Callback liên tục nhận audio chunk từ sounddevice."""
        if status:
            print(f"  ⚠️  Audio status: {status}", file=sys.stderr)
        # Chuyển về mono nếu stereo
        mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        q.put(mono.copy())

    print("\n" + "=" * 55)
    if is_loopback:
        print("🔊 SẴN SÀNG – Đang thu âm thanh hệ thống (YouTube, v.v.)")
    else:
        print("🎤 SẴN SÀNG – Đang chờ giọng nói từ microphone")
    print("=" * 55)

    while True:
        input("\n👉 Nhấn [Enter] để bắt đầu thu âm  (Ctrl+C để thoát)...")

        if is_loopback:
            print("🔴 [ĐANG LẮNG NGHE ÂM THANH HỆ THỐNG...] (Nhấn Ctrl+C để dừng & nhận diện)")
        else:
            print("🔴 [ĐANG THU ÂM...] Hãy nói tiếng Việt. (Nhấn Ctrl+C để dừng & nhận diện)")

        audio_data: list[np.ndarray] = []
        try:
            with sd.InputStream(
                samplerate=device_sr,
                channels=device_channels,
                dtype="float32",
                device=device_index,
                callback=audio_callback,
            ):
                while True:
                    audio_data.append(q.get())
        except KeyboardInterrupt:
            print("\n⏳ [Đã dừng thu âm – đang nhận diện...]")

        if not audio_data:
            print("⚠️  Không có dữ liệu âm thanh nào được ghi lại.\n")
            continue

        # Gộp và nhận diện
        samples = np.concatenate(audio_data).astype(np.float32)

        t0 = time.time()
        text = transcribe_array(recognizer, samples, device_sr)
        elapsed = time.time() - t0
        duration = len(samples) / device_sr

        print("\n" + "=" * 55)
        print("📝 KẾT QUẢ NHẬN DIỆN:")
        print(f"   🇻🇳 VI: {text or '(Không nhận diện được gì)'}")
        print(f"   Audio: {duration:.1f}s  |  Xử lý: {elapsed:.2f}s  |  RTF: {elapsed/duration:.3f}" if duration > 0 else "")
        if args.translate and text:
            print_translations(text, indent="   ")
        print("=" * 55)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nĐã thoát chương trình.")
        sys.exit(0)
