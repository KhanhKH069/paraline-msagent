"""
client/audio_router/get_device.py
Liệt kê và tìm kiếm thiết bị audio được tối ưu hóa cho Windows, Linux, macOS.
Tự động lọc trùng lặp giữa các Host API (MME, DirectSound, WASAPI, WDM-KS) trên Windows.
"""

import logging
import platform
import re
import sys
from typing import List, Optional, Tuple

import sounddevice as sd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("meeting_ai.audio.get_device")


def get_device_category(name: str) -> Tuple[str, str, int]:
    """
    Phân loại thiết bị âm thanh để gán icon, mô tả và thứ tự ưu tiên (priority).
    Priority: số càng nhỏ càng ưu tiên hiển thị trước.
    """
    nl = name.lower()
    if "cable output" in nl or ("cable" in nl and "point" not in nl and "in" not in nl):
        return "🔊", "[Khuyên dùng Meet/Teams]", 1
    if "stereo mix" in nl or "wave out" in nl:
        return "🔊", "[Toàn bộ âm thanh máy tính]", 2
    if "microphone" in nl or "mic" in nl:
        return "🎙", "[Micro đàm thoại]", 3
    if "line in" in nl:
        return "🎙", "[Line In]", 4
    if "monitor" in nl:
        return "🔊", "[System Monitor]", 1
    return "🎙", "[Audio Device]", 5


def get_clean_input_devices() -> List[Tuple[int, dict, str, str, str]]:
    """
    Trả về danh sách thiết bị Input đã được lọc trùng lặp và phân loại sạch sẽ.
    Return: list các tuple (device_index, dev_info, host_api_name, icon, tag)
    """
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    curr_os = platform.system().lower()

    if curr_os == "windows":
        wasapi_idx = next((i for i, h in enumerate(host_apis) if "WASAPI" in h["name"]), None)
        clean_list = []
        seen_sigs = set()

        def _get_sig(dname: str) -> str:
            nl = dname.lower()
            if "cable output" in nl or ("cable" in nl and "point" not in nl):
                return "vbcable"
            if "stereo mix" in nl:
                return "stereomix"
            if "microphone" in nl or "mic" in nl:
                return "microphone"
            if "line in" in nl:
                return "linein"
            clean = re.sub(r"\(.*?\)", "", nl).strip()
            return clean[:14]

        # 1. Quét WASAPI trước (độ trễ thấp, tên đầy đủ, stereo chuẩn)
        if wasapi_idx is not None:
            for i, d in enumerate(devices):
                if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
                    name = d["name"].strip()
                    if "sound mapper" in name.lower() or "primary sound" in name.lower() or "point" in name.lower():
                        continue
                    sig = _get_sig(name)
                    icon, tag, prio = get_device_category(name)
                    clean_list.append((prio, i, d, "WASAPI", icon, tag))
                    seen_sigs.add(sig)

        # 2. Bổ sung các thiết bị độc nhất từ API khác (ví dụ Stereo Mix từ WDM-KS nếu WASAPI không có)
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                name = d["name"].strip()
                if "sound mapper" in name.lower() or "primary sound" in name.lower() or "point" in name.lower():
                    continue
                sig = _get_sig(name)
                if sig not in seen_sigs:
                    hname = host_apis[d["hostapi"]]["name"]
                    icon, tag, prio = get_device_category(name)
                    clean_list.append((prio, i, d, hname, icon, tag))
                    seen_sigs.add(sig)

        # Sắp xếp theo độ ưu tiên
        clean_list.sort(key=lambda x: (x[0], x[1]))
        return [(item[1], item[2], item[3], item[4], item[5]) for item in clean_list]

    else:
        # Linux / macOS
        results = []
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                name = d["name"]
                icon, tag, prio = get_device_category(name)
                hname = host_apis[d["hostapi"]]["name"] if "hostapi" in d else "default"
                results.append((prio, i, d, hname, icon, tag))
        results.sort(key=lambda x: (x[0], x[1]))
        return [(item[1], item[2], item[3], item[4], item[5]) for item in results]


def find_best_input_device() -> Tuple[Optional[int], Optional[dict]]:
    """
    Tự động tìm thiết bị Input tốt nhất cho cuộc họp:
    1. VB-Audio CABLE Output (Windows) hoặc Monitor (Linux)
    2. Stereo Mix
    3. Microphone
    4. Default input device
    """
    clean = get_clean_input_devices()
    if not clean:
        default_in = sd.default.device[0]
        if default_in is not None and default_in >= 0:
            return default_in, sd.query_devices(default_in)
        return None, None

    # Tìm virtual cable hoặc monitor trước
    for idx, d, _, _, _ in clean:
        nl = d["name"].lower()
        if "cable" in nl or "monitor" in nl:
            return idx, d

    # Tìm stereo mix
    for idx, d, _, _, _ in clean:
        if "stereo mix" in d["name"].lower():
            return idx, d

    # Fallback thiết bị đầu tiên trong danh sách sạch
    return clean[0][0], clean[0][1]


def find_device(name: str, kind: str = "input") -> Tuple[Optional[int], Optional[dict]]:
    """
    Tìm thiết bị audio theo tên và loại ('input' hoặc 'output').
    Ưu tiên tìm trong WASAPI trước trên Windows.
    """
    devices = sd.query_devices()
    name_lower = name.lower()

    # Nếu truyền vào là số index
    try:
        idx = int(name)
        if 0 <= idx < len(devices):
            d = devices[idx]
            if (kind == "input" and d["max_input_channels"] > 0) or (kind == "output" and d["max_output_channels"] > 0):
                return idx, d
    except ValueError:
        pass

    # Trên Windows: ưu tiên tìm trong WASAPI trước
    if platform.system().lower() == "windows":
        host_apis = sd.query_hostapis()
        wasapi_idx = next((i for i, h in enumerate(host_apis) if "WASAPI" in h["name"]), None)
        if wasapi_idx is not None:
            # Nếu tìm cable: ưu tiên "cable input" cho output (loa ảo) và "cable output" cho input (mic ảo)
            if "cable" in name_lower:
                sub_target = "cable input" if kind == "output" else "cable output"
                for idx, d in enumerate(devices):
                    if d["hostapi"] == wasapi_idx:
                        ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
                        if ch > 0 and sub_target in d["name"].lower():
                            return idx, d

            for idx, d in enumerate(devices):
                if d["hostapi"] == wasapi_idx:
                    if kind == "input" and d["max_input_channels"] > 0 and name_lower in d["name"].lower():
                        return idx, d
                    elif kind == "output" and d["max_output_channels"] > 0 and name_lower in d["name"].lower():
                        return idx, d

    # Quét toàn bộ (ưu tiên sub_target nếu là cable)
    if "cable" in name_lower:
        sub_target = "cable input" if kind == "output" else "cable output"
        for idx, d in enumerate(devices):
            ch = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
            if ch > 0 and sub_target in d["name"].lower():
                return idx, d

    for idx, d in enumerate(devices):
        if kind == "input" and d["max_input_channels"] > 0 and name_lower in d["name"].lower():
            return idx, d
        elif kind == "output" and d["max_output_channels"] > 0 and name_lower in d["name"].lower():
            return idx, d

    return None, None


def list_devices():
    """In ra danh sách thiết bị audio được làm sạch và phân loại dễ hiểu."""
    print("\n=======================================================")
    print("      DANH SÁCH THIẾT BỊ THU ÂM (AUDIO INPUT)")
    print("=======================================================")
    clean = get_clean_input_devices()
    if not clean:
        print("  ❌ Không tìm thấy thiết bị thu âm nào!")
        return

    for idx, d, hname, icon, tag in clean:
        print(f"  {icon} ID [{idx:2d}] {tag:30s} : {d['name']} ({d['max_input_channels']}ch, {int(d['default_samplerate'])}Hz)")
    print("=======================================================\n")


if __name__ == "__main__":
    list_devices()
    best_idx, best_dev = find_best_input_device()
    if best_dev:
        print(f"🎯 Thiết bị đề xuất tối ưu: ID {best_idx} - {best_dev['name']}")