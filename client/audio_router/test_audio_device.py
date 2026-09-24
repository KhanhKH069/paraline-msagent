"""
client/audio_router/test_audio_device.py
Công cụ kiểm tra & chạy thử thiết bị nhận âm thanh (Audio Input Device Runner).
Tự động phát hiện Virtual Cable (CABLE Output), đo cường độ âm thanh thực tế (VU meter),
và kiểm tra luồng âm thanh loopback từ Virtual Speaker sang Virtual Mic.
"""

import argparse
import math
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Cho phép chạy script trực tiếp từ bất kỳ thư mục nào
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import numpy as np
import sounddevice as sd

from client.audio_router.get_device import (
    find_best_input_device,
    find_device,
    list_devices,
)


def draw_vu_meter(rms: float, peak: float, width: int = 24) -> str:
    """Tạo thanh hiển thị âm lượng dạng ASCII trực quan."""
    if rms <= 1e-5:
        db = -60.0
    else:
        db = 20 * math.log10(rms)
    db = max(-60.0, min(0.0, db))

    # Tỷ lệ từ -60dB (0%) đến 0dB (100%)
    fraction = (db + 60.0) / 60.0
    filled = int(fraction * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {db:5.1f} dB (Peak: {peak:.3f})"


def test_loopback_cable(in_dev_idx: int) -> bool:
    """
    Tự động phát âm thanh thử nghiệm vào CABLE Input và đo tín hiệu thu về từ CABLE Output.
    """
    out_idx, out_dev = find_device("cable", kind="output")
    if out_idx is None or out_dev is None:
        print("\n[INFO] Không tìm thấy 'CABLE Input' để chạy test loopback tự động.")
        return False

    in_dev = sd.query_devices(in_dev_idx)
    sr = int(in_dev["default_samplerate"])

    print("\n-------------------------------------------------------")
    print(f"🔄 ĐANG CHẠY TEST LOOPBACK ẢO (VIRTUAL CABLE SELF-TEST)")
    print(f"   Phát vào : [Dev {out_idx}] {out_dev['name']}")
    print(f"   Thu từ   : [Dev {in_dev_idx}] {in_dev['name']} ({sr} Hz)")
    print("-------------------------------------------------------")

    # Tạo tín hiệu sine 440Hz dài 0.8 giây
    duration = 0.8
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    recorded_chunks = []

    def in_cb(indata, frames, time_info, status):
        recorded_chunks.append(indata.copy())

    try:
        stream_in = sd.InputStream(
            device=in_dev_idx,
            samplerate=sr,
            channels=1,
            dtype="float32",
            callback=in_cb,
        )
        stream_in.start()
        time.sleep(0.05)

        stream_out = sd.OutputStream(
            device=out_idx,
            samplerate=sr,
            channels=1,
            dtype="float32",
        )
        stream_out.start()
        stream_out.write(tone)

        time.sleep(duration + 0.1)
        stream_out.stop()
        stream_out.close()
        stream_in.stop()
        stream_in.close()

        if recorded_chunks:
            all_data = np.concatenate(recorded_chunks).flatten()
            peak = float(np.max(np.abs(all_data)))
            rms = float(np.sqrt(np.mean(all_data**2)))
            print(f"  Tín hiệu thu được: Peak = {peak:.3f} | RMS = {rms:.3f}")
            if peak > 0.05:
                print("  ✅ [THÀNH CÔNG] Tuyến Virtual Cable hoạt động hoàn hảo 100%!")
                print("     Âm thanh phát từ Google Meet (Speaker: CABLE Input)")
                print("     sẽ được app nhận chuẩn xác qua CABLE Output.")
                return True
            else:
                print("  ⚠️ Tín hiệu thu được quá nhỏ hoặc bị mute trên Windows mixer.")
        else:
            print("  ❌ Không nhận được dữ liệu âm thanh từ stream.")
    except Exception as e:
        print(f"  ❌ Lỗi khi kiểm tra loopback: {e}")

    return False


def run_live_listener(dev_idx: int, duration_sec: float = 6.0):
    """Lắng nghe âm thanh thực tế từ thiết bị và vẽ thanh âm lượng real-time."""
    dev_info = sd.query_devices(dev_idx)
    sr = int(dev_info["default_samplerate"])
    name = dev_info["name"]

    print("\n-------------------------------------------------------")
    print(f"🎙 BẮT ĐẦU THU THỬ NGHIỆM TÍN HIỆU ÂM THANH (LIVE VU METER)")
    print(f"   Thiết bị : [Dev {dev_idx}] {name}")
    print(f"   Tần số   : {sr} Hz | Số kênh: {dev_info['max_input_channels']}")
    print(f"   Thời gian: {duration_sec:.0f} giây (Nhấn Ctrl+C để dừng sớm)")
    print("-------------------------------------------------------")
    print("Mẹo: Hãy nói vào micro, hoặc mở một video/bài hát nếu dùng CABLE Output/Stereo Mix!\n")

    chunk_samples = int(sr * 0.1)  # 100ms mỗi frame
    start_time = time.time()
    max_peak_seen = 0.0
    sound_detected = False

    def audio_cb(indata, frames, time_info, status):
        nonlocal max_peak_seen, sound_detected
        chunk = indata.flatten()
        peak = float(np.max(np.abs(chunk)))
        rms = float(np.sqrt(np.mean(chunk**2)))
        if peak > max_peak_seen:
            max_peak_seen = peak
        if rms > 0.005:
            sound_detected = True

        meter = draw_vu_meter(rms, peak)
        elapsed = time.time() - start_time
        remaining = max(0.0, duration_sec - elapsed)
        sys.stdout.write(f"\r  {meter} | Còn lại: {remaining:4.1f}s ")
        sys.stdout.flush()

    try:
        with sd.InputStream(
            device=dev_idx,
            samplerate=sr,
            channels=1,
            dtype="float32",
            blocksize=chunk_samples,
            callback=audio_cb,
        ):
            while time.time() - start_time < duration_sec:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n\nĐã dừng theo yêu cầu người dùng.")
    except Exception as e:
        print(f"\n❌ Lỗi khi mở audio stream: {e}")
        return

    print("\n")
    if sound_detected or max_peak_seen > 0.01:
        print(f"✅ [TÍN HIỆU TỐT] Thiết bị đang nhận âm thanh rõ ràng (Peak: {max_peak_seen:.3f})!")
    else:
        print(f"ℹ️ [IM LẶNG] Chưa phát hiện âm thanh nào đi qua thiết bị này (Peak max: {max_peak_seen:.3f}).")
        if "cable" in name.lower():
            print("   👉 Nếu muốn thu âm thanh cuộc họp (Google Meet / Teams / YouTube):")
            print("      Vào cài đặt âm thanh của Google Meet hoặc Windows,")
            print("      chọn Loa ra (Speaker / Output) là 'CABLE Input (VB-Audio Virtual Cable)'!")
        elif "mic" in name.lower():
            print("   👉 Hãy thử nói to hơn hoặc kiểm tra Micro có bị Mute trên Windows không.")


def main():
    parser = argparse.ArgumentParser(description="Kiểm tra và chạy thiết bị thu âm thanh dự án")
    parser.add_argument("--device", type=str, default=None, help="Tên hoặc ID thiết bị muốn kiểm tra")
    parser.add_argument("--duration", type=float, default=6.0, help="Thời gian thu thử nghiệm (giây)")
    parser.add_argument("--no-loopback", action="store_true", help="Bỏ qua bước test loopback")
    parser.add_argument("--play-mock", action="store_true", help="Tự động phát mock_en.wav vào CABLE Input để giả lập người nói trong Meet")
    args = parser.parse_args()

    print("\n=======================================================")
    print("      MEETING AI ASSISTANT - AUDIO DEVICE RUNNER")
    print("=======================================================")

    # 1. Liệt kê danh sách thiết bị sạch
    list_devices()

    # 2. Xác định thiết bị mục tiêu
    target_idx = None
    target_dev = None

    if args.device is not None:
        target_idx, target_dev = find_device(args.device, kind="input")
        if target_dev is None:
            print(f"❌ Không tìm thấy thiết bị nào khớp với '{args.device}'")
            return
    else:
        target_idx, target_dev = find_best_input_device()
        if target_dev is None:
            print("❌ Không tìm thấy bất kỳ thiết bị thu âm nào trên máy!")
            return

    print(f"🎯 Thiết bị được chọn kiểm tra: ID [{target_idx}] - {target_dev['name']}")

    # 3. Test loopback nếu là CABLE Output
    if not args.no_loopback and "cable" in target_dev["name"].lower():
        test_loopback_cable(target_idx)

    # 4. Phát mock audio nếu có yêu cầu
    if args.play_mock:
        import threading
        out_idx, out_dev = find_device("cable", kind="output")
        if out_idx is not None:
            def _play():
                try:
                    out_sr = int(out_dev["default_samplerate"])
                    wav_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../mock_en.wav"))
                    if os.path.exists(wav_path):
                        import wave
                        with wave.open(wav_path, "rb") as wf:
                            rate = wf.getframerate()
                            data = wf.readframes(wf.getnframes())
                            pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                            if rate != out_sr:
                                x_old = np.linspace(0, 1, len(pcm))
                                x_new = np.linspace(0, 1, int(len(pcm) * out_sr / rate))
                                pcm = np.interp(x_new, x_old, pcm).astype(np.float32)
                    else:
                        # Tự tổng hợp sóng âm kiểm tra tần số thoại (440Hz & 880Hz)
                        t = np.linspace(0, args.duration, int(out_sr * args.duration), endpoint=False)
                        tone1 = 0.3 * np.sin(2 * np.pi * 440 * t)
                        tone2 = 0.2 * np.sin(2 * np.pi * 880 * t)
                        pcm = (tone1 + tone2).astype(np.float32)

                    with sd.OutputStream(device=out_idx, samplerate=out_sr, channels=1, dtype="float32") as s_out:
                        s_out.write(pcm)
                except Exception as exc:
                    print(f"  [MOCK PLAY ERROR] {exc}")
            threading.Thread(target=_play, daemon=True).start()
            print(f"🔊 [MOCK PLAYBACK] Đang phát tín hiệu giả lập vào {out_dev['name']} (CABLE Input)...")
            time.sleep(0.3)

    # 5. Chạy bộ đo âm thanh thực tế
    run_live_listener(target_idx, duration_sec=args.duration)

    print("\n=======================================================")
    print("              HƯỚNG DẪN CẤU HÌNH NHANH")
    print("=======================================================")
    print("1. Google Meet / Microsoft Teams:")
    print("   - Mở Cài đặt (Settings) -> Âm thanh (Audio).")
    print("   - Đổi LOA (Speaker) thành: 'CABLE Input (VB-Audio Virtual Cable)'.")
    print("2. Meeting AI Client:")
    print(f"   - Chọn thiết bị thu là: ID [{target_idx}] {target_dev['name']}.")
    print("   - Ứng dụng sẽ tự động nghe âm thanh từ cuộc họp và dịch realtime.")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
