"""
Dataset Preparation Pipeline — Vietnamese TTS
Bước 1: Cắt audio → Bước 2: Transcribe → Bước 3: Normalize → Bước 4: Tạo list.txt

Chạy: python scripts/prepare_dataset.py --input data/raw_audio/ --speaker nam_bac
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Tuple

# Thêm root vào path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from text.cleaners.vietnamese_cleaners import vietnamese_cleaners  # noqa: E402


# ─── Bước 1: Slice audio ─────────────────────────────────────────────────────

def slice_audio_files(
    input_dir: str,
    output_dir: str,
    min_duration: float = 2.0,
    max_duration: float = 10.0,
    threshold_db: float = -40.0,
    min_silence_duration: float = 0.3,
) -> List[str]:
    """
    Tự động cắt audio dài thành các clip ngắn 2–10 giây.
    Dùng Audio Slicer dựa trên khoảng lặng.

    Args:
        input_dir: Thư mục chứa audio gốc
        output_dir: Thư mục xuất audio đã cắt
        min_duration: Độ dài tối thiểu mỗi clip (giây)
        max_duration: Độ dài tối đa mỗi clip (giây)
        threshold_db: Ngưỡng silence (dB)
        min_silence_duration: Khoảng lặng tối thiểu để cắt (giây)

    Returns:
        Danh sách đường dẫn các file đã cắt
    """
    import soundfile as sf
    import numpy as np

    os.makedirs(output_dir, exist_ok=True)
    input_files = list(Path(input_dir).glob('**/*.wav')) + \
                  list(Path(input_dir).glob('**/*.mp3')) + \
                  list(Path(input_dir).glob('**/*.flac'))

    sliced_files = []
    total_duration = 0.0
    clip_count = 0

    print(f"[Slicer] Tìm thấy {len(input_files)} file audio.")

    for audio_file in input_files:
        try:
            data, sr = sf.read(str(audio_file))
            if data.ndim > 1:
                data = data.mean(axis=1)  # Stereo → Mono

            # Resample về 22050 Hz nếu cần
            if sr != 22050:
                import librosa
                data = librosa.resample(data, orig_sr=sr, target_sr=22050)
                sr = 22050

            # Tính RMS energy theo frame
            frame_size = int(sr * 0.02)  # 20ms frames
            n_frames = len(data) // frame_size

            rms = np.array([
                np.sqrt(np.mean(data[i*frame_size:(i+1)*frame_size]**2))
                for i in range(n_frames)
            ])

            # Chuyển sang dB
            rms_db = 20 * np.log10(rms + 1e-10)
            silence_mask = rms_db < threshold_db

            # Tìm boundary points
            boundaries = [0]
            in_silence = False
            silence_start = 0

            for i, is_silent in enumerate(silence_mask):
                if is_silent and not in_silence:
                    in_silence = True
                    silence_start = i
                elif not is_silent and in_silence:
                    in_silence = False
                    silence_duration = (i - silence_start) * 0.02
                    if silence_duration >= min_silence_duration:
                        cut_point = (silence_start + (i - silence_start) // 2) * frame_size
                        boundaries.append(cut_point)
            boundaries.append(len(data))

            # Tạo clips từ boundaries
            stem = audio_file.stem
            for j in range(len(boundaries) - 1):
                start = boundaries[j]
                end = boundaries[j + 1]
                duration = (end - start) / sr

                if duration < min_duration:
                    continue
                if duration > max_duration:
                    # Cắt tiếp nếu quá dài
                    n_sub = int(duration / max_duration) + 1
                    sub_len = (end - start) // n_sub
                    sub_boundaries = [start + k * sub_len for k in range(n_sub + 1)]
                    sub_boundaries[-1] = end
                    sub_clips = [(sub_boundaries[k], sub_boundaries[k+1]) for k in range(n_sub)]
                else:
                    sub_clips = [(start, end)]

                for k, (s, e) in enumerate(sub_clips):
                    clip = data[s:e]
                    out_name = f"{stem}_{clip_count:05d}.wav"
                    out_path = os.path.join(output_dir, out_name)
                    sf.write(out_path, clip, sr)
                    sliced_files.append(out_path)
                    total_duration += (e - s) / sr
                    clip_count += 1

        except Exception as ex:
            print(f"[Slicer] Lỗi xử lý {audio_file}: {ex}")
            continue

    print(f"[Slicer] Đã tạo {clip_count} clips, tổng {total_duration/3600:.2f} giờ audio.")
    return sliced_files


# ─── Bước 2: Validate transcripts ────────────────────────────────────────────

def validate_transcripts(
    audio_dir: str,
    transcript_dir: str,
) -> List[Tuple[str, str]]:
    """
    Ghép cặp file audio với transcript.
    Mỗi file audio cần có file .txt cùng tên trong transcript_dir.
    Ví dụ: audio/clip_00001.wav ↔ transcripts/clip_00001.txt
    """
    pairs = []
    audio_files = sorted(Path(audio_dir).glob('*.wav'))

    missing = 0
    for af in audio_files:
        tf = Path(transcript_dir) / (af.stem + '.txt')
        if not tf.exists():
            print(f"[Validate] ⚠ Thiếu transcript: {tf.name}")
            missing += 1
            continue
        with open(tf, 'r', encoding='utf-8') as f:
            text = f.read().strip()
        if not text:
            print(f"[Validate] ⚠ Transcript rỗng: {tf.name}")
            missing += 1
            continue
        pairs.append((str(af), text))

    print(f"[Validate] Hợp lệ: {len(pairs)}, thiếu/lỗi: {missing}")
    return pairs


# ─── Bước 3: Normalize text + tạo list.txt ───────────────────────────────────

def create_dataset_list(
    pairs: List[Tuple[str, str]],
    output_path: str,
    speaker_id: str = "0",
    normalize: bool = True,
    val_ratio: float = 0.02,
) -> Tuple[str, str]:
    """
    Tạo file list.txt từ danh sách (audio, transcript) pairs.
    Format: path/to/audio.wav|văn bản đã chuẩn hóa|speaker_id

    Returns:
        Tuple: (train_path, val_path)
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    processed = []
    for audio_path, raw_text in pairs:
        # Normalize văn bản
        if normalize:
            text = vietnamese_cleaners(raw_text)
        else:
            text = raw_text.strip()

        # Bỏ qua nếu text quá ngắn hoặc quá dài
        if len(text) < 3:
            continue
        if len(text) > 500:
            print(f"[List] ⚠ Text quá dài ({len(text)} chars), bỏ qua: {audio_path}")
            continue

        processed.append(f"{audio_path}|{text}|{speaker_id}")

    # Shuffle và split
    import random
    random.seed(42)
    random.shuffle(processed)

    n_val = max(1, int(len(processed) * val_ratio))
    val_data = processed[:n_val]
    train_data = processed[n_val:]

    train_path = output_path.replace('.txt', '') + '_train.txt'
    val_path = output_path.replace('.txt', '') + '_val.txt'
    full_path = output_path

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(processed))
    with open(train_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(train_data))
    with open(val_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(val_data))

    print(f"[List] Tổng: {len(processed)} samples")
    print(f"[List] Train: {len(train_data)} | Val: {len(val_data)}")
    print(f"[List] Đã lưu: {full_path}, {train_path}, {val_path}")

    return train_path, val_path


# ─── Bước 4: Thống kê dataset ────────────────────────────────────────────────

def compute_statistics(list_path: str):
    """In thống kê dataset: số lượng, thời lượng, độ dài text."""
    import soundfile as sf
    import numpy as np

    if not os.path.exists(list_path):
        print(f"[Stats] Không tìm thấy: {list_path}")
        return

    durations = []
    text_lengths = []
    errors = 0

    with open(list_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    for line in lines:
        parts = line.split('|')
        if len(parts) < 2:
            errors += 1
            continue

        audio_path = parts[0]
        text = parts[1]
        text_lengths.append(len(text))

        try:
            info = sf.info(audio_path)
            durations.append(info.duration)
        except Exception:
            errors += 1

    durations = np.array(durations)
    text_lengths = np.array(text_lengths)

    print("\n" + "═" * 50)
    print("  DATASET STATISTICS")
    print("═" * 50)
    print(f"  Tổng samples:         {len(lines)}")
    print(f"  Lỗi:                  {errors}")
    print(f"  Tổng thời lượng:      {durations.sum()/3600:.2f} giờ")
    print(f"  Thời lượng TB:        {durations.mean():.2f}s")
    print(f"  Thời lượng min:       {durations.min():.2f}s")
    print(f"  Thời lượng max:       {durations.max():.2f}s")
    print(f"  Độ dài text TB:       {text_lengths.mean():.0f} ký tự")
    print(f"  Độ dài text min:      {text_lengths.min()} ký tự")
    print(f"  Độ dài text max:      {text_lengths.max()} ký tự")
    print("═" * 50 + "\n")

    # Cảnh báo
    if durations.sum() / 3600 < 1.0:
        print("⚠ CẢNH BÁO: Tổng thời lượng < 1 giờ. Nên thu thêm audio.")
    if len(durations[durations < 2.0]) > len(durations) * 0.1:
        print("⚠ CẢNH BÁO: Nhiều clip < 2s. Kiểm tra lại slice_audio.")
    if len(durations[durations > 10.0]) > 0:
        print(f"⚠ CẢNH BÁO: {len(durations[durations > 10.0])} clip > 10s. Cần cắt lại.")


# ─── Main pipeline ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Prepare Vietnamese TTS Dataset')
    parser.add_argument('--input', type=str, required=True,
                        help='Thư mục audio gốc (raw_audio/)')
    parser.add_argument('--transcripts', type=str, default='data/transcripts',
                        help='Thư mục transcript .txt')
    parser.add_argument('--sliced_output', type=str, default='data/sliced_audio',
                        help='Thư mục audio đã cắt')
    parser.add_argument('--list_output', type=str, default='dataset/list.txt',
                        help='Đường dẫn xuất list.txt')
    parser.add_argument('--speaker', type=str, default='0',
                        help='Speaker ID (0, 1, 2... hoặc tên)')
    parser.add_argument('--skip_slice', action='store_true',
                        help='Bỏ qua bước cắt audio (nếu đã cắt rồi)')
    parser.add_argument('--stats_only', action='store_true',
                        help='Chỉ tính thống kê')
    args = parser.parse_args()

    if args.stats_only:
        compute_statistics(args.list_output)
        return

    print("\n🎙️  Vietnamese TTS Dataset Preparation\n")

    # Bước 1: Slice
    if not args.skip_slice:
        print("📌 Bước 1: Cắt audio...")
        sliced = slice_audio_files(args.input, args.sliced_output)
    else:
        sliced = list(Path(args.sliced_output).glob('*.wav'))
        print(f"[Slice] Bỏ qua — dùng {len(sliced)} file có sẵn.")

    # Bước 2: Validate transcripts
    print("\n📌 Bước 2: Validate transcripts...")
    pairs = validate_transcripts(args.sliced_output, args.transcripts)

    if not pairs:
        print("❌ Không có cặp audio-transcript hợp lệ. Dừng lại.")
        return

    # Bước 3: Tạo list.txt
    print("\n📌 Bước 3: Tạo dataset list...")
    os.makedirs(os.path.dirname(args.list_output) or '.', exist_ok=True)
    train_path, val_path = create_dataset_list(
        pairs, args.list_output, speaker_id=args.speaker
    )

    # Bước 4: Thống kê
    print("\n📌 Bước 4: Thống kê dataset...")
    compute_statistics(args.list_output)

    print("\n✅ Hoàn thành! Sẵn sàng để training.\n")
    print("   Chạy training: python training/train.py --config configs/base_vi.json")


if __name__ == '__main__':
    main()
