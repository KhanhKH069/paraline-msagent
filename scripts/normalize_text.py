"""
Text Normalization Script — standalone
Chuẩn hóa file transcript trước khi đưa vào dataset.

Chạy:
    python scripts/normalize_text.py \
        --input data/transcripts/ \
        --output data/transcripts_normalized/
"""

import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from text.cleaners.vietnamese_cleaners import vietnamese_cleaners  # noqa: E402


def normalize_file(input_path: str, output_path: str) -> int:
    """Normalize 1 file transcript. Trả về số thay đổi."""
    with open(input_path, 'r', encoding='utf-8') as f:
        original = f.read()

    normalized = vietnamese_cleaners(original)
    changes = original != normalized

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(normalized)

    return int(changes)


def normalize_directory(input_dir: str, output_dir: str) -> dict:
    """Normalize tất cả file .txt trong thư mục."""
    txt_files = sorted(Path(input_dir).glob('*.txt'))
    stats = {'total': len(txt_files), 'changed': 0, 'errors': 0}

    for tf in txt_files:
        out_path = os.path.join(output_dir, tf.name)
        try:
            changed = normalize_file(str(tf), out_path)
            stats['changed'] += changed
        except Exception as e:
            print(f"  ❌ Lỗi {tf.name}: {e}")
            stats['errors'] += 1

    return stats


def normalize_list_file(list_path: str, output_path: str):
    """
    Normalize tất cả transcript trong file list.txt.
    Format: audio_path|transcript|speaker_id
    """
    lines_in = []
    with open(list_path, 'r', encoding='utf-8') as f:
        lines_in = [line.strip() for line in f if line.strip()]

    lines_out = []
    changed = 0
    for line in lines_in:
        parts = line.split('|')
        if len(parts) < 2:
            lines_out.append(line)
            continue

        original_text = parts[1]
        normalized_text = vietnamese_cleaners(original_text)
        if normalized_text != original_text:
            changed += 1
        parts[1] = normalized_text
        lines_out.append('|'.join(parts))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines_out))

    print(f"[Normalize] {changed}/{len(lines_in)} dòng đã thay đổi → {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Vietnamese Text Normalizer')
    parser.add_argument('--input', type=str, required=True,
                        help='File list.txt hoặc thư mục transcript')
    parser.add_argument('--output', type=str, required=True,
                        help='File output hoặc thư mục output')
    parser.add_argument('--show_diff', action='store_true',
                        help='In ra các thay đổi')
    args = parser.parse_args()

    if os.path.isfile(args.input):
        # Normalize file list.txt
        normalize_list_file(args.input, args.output)
    elif os.path.isdir(args.input):
        # Normalize thư mục
        stats = normalize_directory(args.input, args.output)
        print(f"\n[Normalize] Tổng: {stats['total']} | Thay đổi: {stats['changed']} | Lỗi: {stats['errors']}")
    else:
        print(f"❌ Không tìm thấy: {args.input}")

    # Demo interactive nếu không có args
    if args.show_diff:
        print("\n=== Interactive Test ===")
        print("(Nhập văn bản để xem kết quả chuẩn hóa, Ctrl+C để thoát)\n")
        try:
            while True:
                text = input("IN : ").strip()
                if text:
                    result = vietnamese_cleaners(text)
                    print(f"OUT: {result}\n")
        except (KeyboardInterrupt, EOFError):
            print("\nThoát.")


if __name__ == '__main__':
    main()
