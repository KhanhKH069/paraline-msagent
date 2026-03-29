"""
Standalone audio slicer script.
Chạy: python scripts/slice_audio.py --input data/raw_audio/ --output data/sliced_audio/
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.prepare_dataset import slice_audio_files  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Thư mục audio gốc')
    parser.add_argument('--output', required=True, help='Thư mục audio đã cắt')
    parser.add_argument('--min_duration', type=float, default=2.0)
    parser.add_argument('--max_duration', type=float, default=10.0)
    parser.add_argument('--threshold_db', type=float, default=-40.0)
    parser.add_argument('--min_silence', type=float, default=0.3)
    args = parser.parse_args()

    sliced = slice_audio_files(
        args.input, args.output,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        threshold_db=args.threshold_db,
        min_silence_duration=args.min_silence,
    )
    print(f"\nĐã tạo {len(sliced)} clips tại: {args.output}")


if __name__ == '__main__':
    main()
