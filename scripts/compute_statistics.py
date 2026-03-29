"""
Dataset Statistics — Vietnamese Bert-VITS2
In thống kê chi tiết về dataset.

Chạy: python scripts/compute_statistics.py --dataset dataset/list.txt
"""

import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def compute_statistics(list_path: str, check_audio: bool = True):
    """In thống kê đầy đủ."""
    import numpy as np

    if not os.path.exists(list_path):
        print(f"❌ Không tìm thấy: {list_path}")
        return

    lines = []
    with open(list_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    durations, text_lengths, speakers = [], [], []
    missing_audio = 0

    for line in lines:
        parts = line.split('|')
        if len(parts) < 2:
            continue

        audio_path, text = parts[0], parts[1]
        spk = int(parts[2]) if len(parts) > 2 else 0
        text_lengths.append(len(text))
        speakers.append(spk)

        if check_audio and os.path.exists(audio_path):
            try:
                import soundfile as sf
                info = sf.info(audio_path)
                durations.append(info.duration)
            except Exception:
                missing_audio += 1
        elif not os.path.exists(audio_path):
            missing_audio += 1

    durations = np.array(durations) if durations else np.array([0.0])
    text_lengths = np.array(text_lengths)
    n_speakers = len(set(speakers))

    print("\n" + "═" * 56)
    print("  📊  DATASET STATISTICS — Vietnamese TTS")
    print("═" * 56)
    print(f"  File:                  {list_path}")
    print(f"  Tổng samples:          {len(lines):,}")
    print(f"  Audio bị thiếu:        {missing_audio}")
    print(f"  Số speakers:           {n_speakers}")
    print()
    if len(durations) > 1:
        print("  ── Audio Duration ──────────────────────────")
        print(f"  Tổng:                  {durations.sum()/3600:.2f} giờ")
        print(f"  Trung bình:            {durations.mean():.2f}s")
        print(f"  Min / Max:             {durations.min():.2f}s / {durations.max():.2f}s")
        print(f"  Clips < 2s:            {(durations < 2.0).sum()}")
        print(f"  Clips > 10s:           {(durations > 10.0).sum()}")
    print()
    print("  ── Text Length (ký tự) ─────────────────────")
    print(f"  Trung bình:            {text_lengths.mean():.0f}")
    print(f"  Min / Max:             {text_lengths.min()} / {text_lengths.max()}")
    print("  Phân phối:")
    bins = [(0,30), (30,60), (60,100), (100,200), (200,500)]
    for lo, hi in bins:
        count = ((text_lengths >= lo) & (text_lengths < hi)).sum()
        bar = '█' * (count * 20 // len(text_lengths))
        print(f"    {lo:3d}–{hi:3d} ký tự: {count:5d} {bar}")
    print()

    # Khuyến nghị
    print("  ── Khuyến nghị ─────────────────────────────")
    total_h = durations.sum() / 3600
    if total_h < 1.0:
        print(f"  ⚠ Tổng audio {total_h:.2f}h < 1h. Cần thu thêm.")
    elif total_h >= 1.0 and total_h < 2.0:
        print(f"  ✓ {total_h:.2f}h — Đủ để train cơ bản (có thể clone giọng).")
    else:
        print(f"  ✓ {total_h:.2f}h — Tốt! Chất lượng sẽ cao.")

    if missing_audio > 0:
        print(f"  ⚠ {missing_audio} file audio bị thiếu — kiểm tra đường dẫn.")

    print("═" * 56 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, default='dataset/list.txt')
    parser.add_argument('--no_audio_check', action='store_true')
    args = parser.parse_args()
    compute_statistics(args.dataset, check_audio=not args.no_audio_check)


if __name__ == '__main__':
    main()
