"""
Batch Inference — Vietnamese Bert-VITS2
Tổng hợp nhiều câu từ file text hoặc stdin

Chạy:
    python inference/batch_infer.py \
        --input texts.txt \
        --checkpoint checkpoints/G_100000.pth \
        --output_dir outputs/batch/
"""

import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from inference.infer import VietnameseTTS  # noqa: E402


def batch_synthesize(
    tts: VietnameseTTS,
    texts: list,
    output_dir: str,
    speaker_id: int = 0,
    noise_scale: float = 0.667,
    length_scale: float = 1.0,
    prefix: str = 'output',
):
    """
    Tổng hợp danh sách câu, lưu thành file WAV đánh số.

    Args:
        tts: VietnameseTTS instance
        texts: Danh sách văn bản
        output_dir: Thư mục output
        speaker_id: Speaker ID
        noise_scale: Variance của prior
        length_scale: Tốc độ đọc
        prefix: Prefix tên file

    Returns:
        Danh sách đường dẫn file đã tạo
    """
    os.makedirs(output_dir, exist_ok=True)
    output_files = []
    total = len(texts)

    print(f"\n[Batch] Tổng hợp {total} câu → {output_dir}/\n")

    for i, text in enumerate(texts):
        text = text.strip()
        if not text:
            continue

        out_path = os.path.join(output_dir, f'{prefix}_{i+1:04d}.wav')
        print(f"[{i+1}/{total}] {text[:60]}{'...' if len(text)>60 else ''}")

        try:
            tts.synthesize_to_file(
                text, out_path,
                speaker_id=speaker_id,
                noise_scale=noise_scale,
                length_scale=length_scale,
            )
            output_files.append(out_path)
        except Exception as e:
            print(f"  ❌ Lỗi: {e}")

    print(f"\n✅ Hoàn thành: {len(output_files)}/{total} file.")
    return output_files


def main():
    parser = argparse.ArgumentParser(description='Batch Vietnamese TTS Inference')
    parser.add_argument('--input', type=str, default=None,
                        help='File text (mỗi dòng 1 câu). Nếu bỏ qua → đọc từ stdin.')
    parser.add_argument('--checkpoint', type=str, required=True)
    parser.add_argument('--config', type=str, default=None)
    parser.add_argument('--output_dir', type=str, default='outputs/batch')
    parser.add_argument('--speaker', type=int, default=0)
    parser.add_argument('--noise_scale', type=float, default=0.667)
    parser.add_argument('--length_scale', type=float, default=1.0)
    parser.add_argument('--prefix', type=str, default='output')
    args = parser.parse_args()

    # Đọc danh sách câu
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            texts = [line.strip() for line in f if line.strip()]
    else:
        print("Nhập văn bản (Ctrl+D để kết thúc):")
        texts = sys.stdin.read().splitlines()

    if not texts:
        print("Không có văn bản nào để tổng hợp.")
        return

    # Load model
    tts = VietnameseTTS(args.checkpoint, args.config)

    # Batch synthesize
    batch_synthesize(
        tts, texts,
        output_dir=args.output_dir,
        speaker_id=args.speaker,
        noise_scale=args.noise_scale,
        length_scale=args.length_scale,
        prefix=args.prefix,
    )


if __name__ == '__main__':
    main()
