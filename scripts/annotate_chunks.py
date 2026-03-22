"""
scripts/annotate_chunks.py

Thêm chunk annotation vào processed JSONL dataset.
Chạy sau prepare_data.py.

Usage:
    python scripts/annotate_chunks.py
    python scripts/annotate_chunks.py --input data/processed/train.jsonl --overwrite
"""

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chunker import get_chunker, assign_context_weights


LANG_MAP = {
    "jpn_Jpan": "ja",
    "eng_Latn": "en",
    "vie_Latn": "vi",
}


def annotate_file(input_path: str, output_path: str):
    chunkers = {}

    def get_c(lang_code: str):
        lang = LANG_MAP.get(lang_code, "en")
        if lang not in chunkers:
            try:
                chunkers[lang] = get_chunker(lang)
            except Exception as e:
                print(f"[WARN] {lang}: {e}")
                chunkers[lang] = None
        return chunkers[lang]

    records = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line.strip()))

    annotated = []
    for rec in tqdm(records, desc=f"Annotating {Path(input_path).name}"):
        if "src_chunks" not in rec:
            src_lang = rec.get("src_lang", "eng_Latn")
            chunker = get_c(src_lang)
            if chunker and rec.get("src"):
                try:
                    chunked = chunker.chunk(rec["src"])
                    chunked = assign_context_weights(chunked)
                    rec["src_chunks"] = chunked.to_dict()
                except Exception:
                    rec["src_chunks"] = {"chunks": []}
        annotated.append(rec)

    with open(output_path, "w", encoding="utf-8") as f:
        for rec in annotated:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Annotated {len(annotated)} records → {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/processed")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    processed_dir = Path(args.dir)
    for split in ["train", "valid", "test"]:
        in_path = processed_dir / f"{split}.jsonl"
        out_path = processed_dir / f"{split}_chunked.jsonl"

        if not in_path.exists():
            print(f"[SKIP] {in_path} not found")
            continue

        if out_path.exists() and not args.overwrite:
            print(f"[SKIP] {out_path} already exists (use --overwrite)")
            continue

        annotate_file(str(in_path), str(out_path))

    print("\nChunk annotation complete! ✅")


if __name__ == "__main__":
    main()
