"""
Synthetic Dataset Generator — Vietnamese TTS (VITS2)
====================================================
Tổng hợp audio từ câu văn tiếng Việt dùng gTTS, sau đó:
  1. Convert MP3 → WAV 22050 Hz mono (pydub + ffmpeg)
  2. Normalize text (vietnamese_cleaners)
  3. Tạo dataset/list.txt, dataset/train.txt, dataset/val.txt

Cú pháp:
  python scripts/generate_synthetic.py
  python scripts/generate_synthetic.py --limit 50
  python scripts/generate_synthetic.py --sentences data/sentences/ --workers 4 --resume

Yêu cầu:
  pip install gtts pydub tqdm
  ffmpeg phải có trong PATH (brew install ffmpeg / apt install ffmpeg / choco install ffmpeg)
"""

import sys
import time
import random
import argparse
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── Thêm project root vào path ──────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ─── Imports ──────────────────────────────────────────────────────────────────
try:
    from gtts import gTTS
except ImportError:
    print("❌ Thiếu gTTS. Chạy: pip install gtts")
    sys.exit(1)

try:
    from pydub import AudioSegment
    import pydub.utils
    # Set explicit path for ffmpeg installed via winget
    ffmpeg_cmd = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe"
    ffprobe_cmd = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffprobe.exe"
    
    if ffmpeg_cmd.exists():
        AudioSegment.converter = str(ffmpeg_cmd)
        pydub.utils.get_prober_name = lambda: str(ffprobe_cmd)
except ImportError:
    print("❌ Thiếu pydub. Chạy: pip install pydub")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    print("❌ Thiếu tqdm. Chạy: pip install tqdm")
    sys.exit(1)

try:
    from text.cleaners.vietnamese_cleaners import vietnamese_cleaners
    USE_CLEANER = True
except Exception:
    print("⚠ Không load được vietnamese_cleaners — dùng text gốc.")
    USE_CLEANER = False


# ─── Load sentences ───────────────────────────────────────────────────────────

def load_sentences(source: str) -> list[str]:
    """
    Load câu từ file hoặc toàn bộ thư mục.
    Bỏ qua dòng trống, comment (#), và câu quá ngắn/dài.
    """
    source_path = Path(source)
    files = []

    if source_path.is_file():
        files = [source_path]
    elif source_path.is_dir():
        files = sorted(source_path.glob('*.txt'))
        if not files:
            print(f"❌ Không tìm thấy file .txt nào trong {source}")
            sys.exit(1)
    else:
        print(f"❌ Không tìm thấy: {source}")
        sys.exit(1)

    sentences = []
    seen = set()

    for f in files:
        with open(f, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if len(line) < 5 or len(line) > 300:
                    continue
                h = hashlib.md5(line.encode()).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                sentences.append(line)

    print(f"[Loader] Đã load {len(sentences)} câu từ {len(files)} file.")
    return sentences


# ─── Synthesize one sentence ─────────────────────────────────────────────────

def synthesize_one(
    idx: int,
    text: str,
    output_dir: Path,
    speaker_id: str = "0",
    slow: bool = False,
    sample_rate: int = 22050,
) -> tuple[str, str] | None:
    """
    Tổng hợp một câu → WAV.
    Trả về (wav_path, normalized_text) hoặc None nếu lỗi.
    """
    wav_name = f"clip_{idx:06d}.wav"
    wav_path = output_dir / wav_name

    if wav_path.exists():
        # Resume: đã có rồi, dùng lại
        normalized = vietnamese_cleaners(text) if USE_CLEANER else text.strip()
        return (str(wav_path), normalized)

    mp3_path = output_dir / f"_tmp_{idx:06d}.mp3"

    try:
        # Bước 1: gTTS → mp3
        tts = gTTS(text=text, lang='vi', slow=slow)
        tts.save(str(mp3_path))

        # Bước 2: pydub → WAV 22050 Hz mono 16-bit
        audio = AudioSegment.from_mp3(str(mp3_path))
        audio = audio.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
        audio.export(str(wav_path), format='wav')

        # Xóa file tạm
        mp3_path.unlink(missing_ok=True)

        # Normalize text
        normalized = vietnamese_cleaners(text) if USE_CLEANER else text.strip()
        if len(normalized) < 3:
            wav_path.unlink(missing_ok=True)
            return None

        return (str(wav_path), normalized)

    except Exception:
        mp3_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        return None


# ─── Main pipeline ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Synthetic Vietnamese TTS Dataset Generator (gTTS → VITS2 format)"
    )
    parser.add_argument(
        '--sentences', type=str,
        default='data/sentences',
        help='File hoặc thư mục chứa câu văn tiếng Việt (default: data/sentences/)'
    )
    parser.add_argument(
        '--output_dir', type=str,
        default='data/synthetic_audio',
        help='Thư mục xuất file WAV (default: data/synthetic_audio/)'
    )
    parser.add_argument(
        '--dataset_dir', type=str,
        default='dataset',
        help='Thư mục xuất list.txt / train.txt / val.txt (default: dataset/)'
    )
    parser.add_argument(
        '--speaker', type=str,
        default='0',
        help='Speaker ID (default: 0)'
    )
    parser.add_argument(
        '--workers', type=int,
        default=4,
        help='Số luồng song song (default: 4). Tăng lên để nhanh hơn, giảm nếu bị rate-limit.'
    )
    parser.add_argument(
        '--val_ratio', type=float,
        default=0.02,
        help='Tỉ lệ validation set (default: 0.02 = 2%%)'
    )
    parser.add_argument(
        '--limit', type=int,
        default=0,
        help='Giới hạn số câu (0 = không giới hạn, dùng khi test)'
    )
    parser.add_argument(
        '--slow', action='store_true',
        help='gTTS đọc chậm (tốt hơn cho kiểm tra)'
    )
    parser.add_argument(
        '--resume', action='store_true',
        help='Bỏ qua file WAV đã tổng hợp (tiếp tục từ điểm dừng)'
    )
    parser.add_argument(
        '--sample_rate', type=int,
        default=22050,
        help='Sample rate output WAV (default: 22050)'
    )
    parser.add_argument(
        '--delay', type=float,
        default=0.2,
        help='Độ trễ giữa các request (giây, default: 0.2) để tránh rate-limit'
    )
    args = parser.parse_args()

    print("\n🎙️  Synthetic Dataset Generator — Vietnamese TTS\n" + "=" * 50)

    # ── Load sentences ────────────────────────────────────────────────────────
    sentences = load_sentences(args.sentences)

    if args.limit > 0:
        sentences = sentences[:args.limit]
        print(f"[Limit] Chỉ xử lý {len(sentences)} câu đầu.")

    random.seed(42)
    random.shuffle(sentences)

    output_dir = ROOT / args.output_dir
    dataset_dir = ROOT / args.dataset_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    # ── Generate ──────────────────────────────────────────────────────────────
    print(f"\n📌 Đang tổng hợp {len(sentences)} câu → {output_dir}")
    print(f"   Workers: {args.workers}  |  Delay: {args.delay}s  |  Sample rate: {args.sample_rate}Hz\n")

    results: list[tuple[str, str]] = []
    errors = 0

    # Xây dựng danh sách task
    tasks = [(i, text) for i, text in enumerate(sentences)]

    def worker_fn(task):
        idx, text = task
        time.sleep(args.delay * (idx % args.workers))  # stagger để tránh ban
        return synthesize_one(
            idx, text, output_dir,
            speaker_id=args.speaker,
            slow=args.slow,
            sample_rate=args.sample_rate
        )

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(worker_fn, t): t for t in tasks}
        with tqdm(total=len(tasks), desc="Synthesizing", unit="clip") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)
                else:
                    errors += 1
                pbar.update(1)
                pbar.set_postfix(ok=len(results), err=errors)

    print(f"\n✅ Tổng hợp xong: {len(results)} thành công, {errors} lỗi.")

    if not results:
        print("❌ Không có file nào thành công. Kiểm tra lại kết nối internet và ffmpeg.")
        sys.exit(1)

    # ── Tạo list.txt, train.txt, val.txt ─────────────────────────────────────
    print("\n📌 Tạo dataset list files...")

    random.shuffle(results)
    n_val = max(1, int(len(results) * args.val_ratio))
    val_data = results[:n_val]
    train_data = results[n_val:]

    def write_list(pairs, path, spk_id):
        lines = [f"{wav}|{text}|{spk_id}" for wav, text in pairs]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return path

    list_path   = dataset_dir / 'list.txt'
    train_path  = dataset_dir / 'train.txt'
    val_path    = dataset_dir / 'val.txt'

    write_list(results, list_path, args.speaker)
    write_list(train_data, train_path, args.speaker)
    write_list(val_data, val_path, args.speaker)

    # ── Thống kê ─────────────────────────────────────────────────────────────
    print("\n" + "═" * 50)
    print("  DATASET STATISTICS")
    print("═" * 50)
    print(f"  Tổng samples:    {len(results)}")
    print(f"  Train:           {len(train_data)}")
    print(f"  Val:             {len(val_data)}")
    print(f"  Lỗi bỏ qua:      {errors}")

    try:
        import soundfile as sf
        import numpy as np
        durations = []
        for wav_path, _ in results:
            try:
                info = sf.info(wav_path)
                durations.append(info.duration)
            except Exception:
                pass
        if durations:
            d = np.array(durations)
            total_h = d.sum() / 3600
            print(f"  Tổng thời lượng: {total_h:.2f} giờ ({d.sum():.0f}s)")
            print(f"  Thời lượng TB:   {d.mean():.2f}s")
            print(f"  Min/Max:         {d.min():.2f}s / {d.max():.2f}s")
            if total_h < 1.0:
                print("\n⚠ CẢNH BÁO: Tổng thời lượng < 1 giờ. Cần thêm dữ liệu.")
    except ImportError:
        pass

    print("═" * 50)
    print(f"\n  📂 list.txt  → {list_path}")
    print(f"  📂 train.txt → {train_path}")
    print(f"  📂 val.txt   → {val_path}")
    print("\n  ▶ Chạy training:")
    print("    python training/train.py --config configs/base_vi.json\n")


if __name__ == '__main__':
    main()
