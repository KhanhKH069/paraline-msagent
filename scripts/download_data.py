"""
scripts/download_data.py

Tải parallel corpus từ OPUS hoặc HuggingFace datasets.
Hỗ trợ: Tatoeba, OpenSubtitles, CCAligned, WikiMatrix, JESC.

Usage:
    python scripts/download_data.py --source opus --lang-pair ja-en --limit 200000
    python scripts/download_data.py --source opus --lang-pair en-vi --limit 200000
    python scripts/download_data.py --source hf   --dataset Helsinki-NLP/tatoeba_mt --src ja --tgt en
    python scripts/download_data.py --all          # Download tất cả (mất nhiều thời gian)
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


LANG_PAIR_DIRS = {
    "ja-en": "data/raw/ja_en",
    "en-ja": "data/raw/ja_en",
    "en-vi": "data/raw/en_vi",
    "vi-en": "data/raw/en_vi",
    "ja-vi": "data/raw/ja_vi",
    "vi-ja": "data/raw/ja_vi",
}

# OPUS dataset names per lang pair
OPUS_DATASETS = {
    "ja-en": ["Tatoeba", "JESC", "TED2020", "OpenSubtitles"],
    "en-vi": ["CCAligned", "Tatoeba", "TED2020", "OpenSubtitles", "WikiMatrix"],
    "ja-vi": ["Tatoeba", "WikiMatrix"],
}


def download_from_hf_datasets(
    dataset_name: str,
    src_lang: str,
    tgt_lang: str,
    out_dir: str,
    limit: Optional[int] = None,
):
    """Tải từ HuggingFace datasets."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("Install: pip install datasets")
        return

    print(f"Loading HF dataset: {dataset_name} ({src_lang}→{tgt_lang})...")
    try:
        ds = load_dataset(dataset_name, lang1=src_lang, lang2=tgt_lang, split="train")
    except Exception:
        try:
            ds = load_dataset(dataset_name, f"{src_lang}-{tgt_lang}", split="train")
        except Exception as e:
            print(f"[ERROR] Could not load {dataset_name}: {e}")
            return

    pairs: List[Tuple[str, str]] = []
    for item in ds:
        if "translation" in item:
            s = item["translation"].get(src_lang, "")
            t = item["translation"].get(tgt_lang, "")
        elif src_lang in item and tgt_lang in item:
            s = item[src_lang]
            t = item[tgt_lang]
        else:
            continue
        if s and t:
            pairs.append((s.strip(), t.strip()))
        if limit and len(pairs) >= limit:
            break

    _save_pairs(pairs, out_dir)
    print(f"  Saved {len(pairs)} pairs → {out_dir}")


def download_from_opus(
    src_lang: str,
    tgt_lang: str,
    out_dir: str,
    corpus_names: Optional[List[str]] = None,
    limit: Optional[int] = None,
):
    """
    Tải từ OPUS qua opustools hoặc gợi ý manual download.
    """
    try:
        from opustools import OpusGet
        _download_opus_api(src_lang, tgt_lang, out_dir, corpus_names, limit)
    except ImportError:
        _print_manual_download_instructions(src_lang, tgt_lang, out_dir, corpus_names)


def _download_opus_api(src_lang, tgt_lang, out_dir, corpus_names, limit):
    from opustools import OpusGet

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    pairs = []

    corpora = corpus_names or OPUS_DATASETS.get(f"{src_lang}-{tgt_lang}", ["Tatoeba"])

    for corpus in corpora:
        print(f"  Fetching {corpus} ({src_lang}↔{tgt_lang})...")
        try:
            og = OpusGet(
                source=src_lang,
                target=tgt_lang,
                corpus=corpus,
                release="latest",
                preprocess="moses",
                download_dir=f"/tmp/opus_{corpus}_{src_lang}_{tgt_lang}",
            )
            og.get_files()

            src_file = f"/tmp/opus_{corpus}_{src_lang}_{tgt_lang}/{corpus}.{src_lang}"
            tgt_file = f"/tmp/opus_{corpus}_{src_lang}_{tgt_lang}/{corpus}.{tgt_lang}"

            if Path(src_file).exists() and Path(tgt_file).exists():
                with open(src_file) as sf, open(tgt_file) as tf:
                    for s, t in zip(sf, tf):
                        pairs.append((s.strip(), t.strip()))
                        if limit and len(pairs) >= limit:
                            break
        except Exception as e:
            print(f"  [WARN] {corpus}: {e}")

        if limit and len(pairs) >= limit:
            break

    _save_pairs(pairs, out_dir)
    print(f"  Total saved: {len(pairs)} pairs → {out_dir}")


def _print_manual_download_instructions(src_lang, tgt_lang, out_dir, corpus_names):
    """Fallback: hướng dẫn download thủ công."""
    corpora = corpus_names or OPUS_DATASETS.get(f"{src_lang}-{tgt_lang}", ["Tatoeba"])
    print(f"\n[INFO] opustools không có sẵn. Download thủ công:")
    print(f"  URL: https://opus.nlpl.eu/")
    for corpus in corpora:
        print(f"  → {corpus}: https://opus.nlpl.eu/{corpus}/corpus/v1/moses/{src_lang}-{tgt_lang}.txt.zip")
    print(f"  Sau khi download, extract và đặt vào:")
    print(f"    {out_dir}/src.txt  (câu {src_lang})")
    print(f"    {out_dir}/tgt.txt  (câu {tgt_lang})")


def _save_pairs(pairs: List[Tuple[str, str]], out_dir: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    tsv_path = Path(out_dir) / "pairs.tsv"
    src_path = Path(out_dir) / "src.txt"
    tgt_path = Path(out_dir) / "tgt.txt"

    with open(tsv_path, "w", encoding="utf-8") as f:
        for s, t in pairs:
            f.write(f"{s}\t{t}\n")

    with open(src_path, "w", encoding="utf-8") as f:
        for s, _ in pairs:
            f.write(s + "\n")

    with open(tgt_path, "w", encoding="utf-8") as f:
        for _, t in pairs:
            f.write(t + "\n")

    # Metadata
    meta = {
        "n_pairs": len(pairs),
        "src_path": str(src_path),
        "tgt_path": str(tgt_path),
    }
    with open(Path(out_dir) / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def load_and_merge_domain_data(out_dir: str, extra_weight: int = 3):
    """
    Merge domain-specific corpus vào raw data với upsampling.
    extra_weight: lặp lại n lần để tăng trọng số domain data.
    """
    domain_dirs = [
        "data/raw/domain/tech_support",
        "data/raw/domain/meeting_transcripts",
        "data/raw/domain/business_email",
    ]

    all_pairs = []
    for domain_dir in domain_dirs:
        tsv_file = Path(domain_dir) / "pairs_ja_en_vi.tsv"
        if not tsv_file.exists():
            continue

        pairs_ja_en = []
        pairs_en_vi = []
        pairs_ja_vi = []

        with open(tsv_file, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                ja = row.get("ja", "").strip()
                en = row.get("en", "").strip()
                vi = row.get("vi", "").strip()
                if ja and en:
                    pairs_ja_en.append((ja, en))
                if en and vi:
                    pairs_en_vi.append((en, vi))
                if ja and vi:
                    pairs_ja_vi.append((ja, vi))

        # Upsample domain data
        for pair_list, pair_dir in [
            (pairs_ja_en, "data/raw/ja_en"),
            (pairs_en_vi, "data/raw/en_vi"),
            (pairs_ja_vi, "data/raw/ja_vi"),
        ]:
            if pair_list:
                upsampled = pair_list * extra_weight
                # Append to existing
                tsv_out = Path(pair_dir) / "pairs_domain.tsv"
                Path(pair_dir).mkdir(parents=True, exist_ok=True)
                with open(tsv_out, "a", encoding="utf-8") as f:
                    for s, t in upsampled:
                        f.write(f"{s}\t{t}\n")
                print(f"  Appended {len(upsampled)} domain pairs → {tsv_out}")

    print("\nDomain data merged ✅")


def main():
    parser = argparse.ArgumentParser(description="Download parallel corpora")
    parser.add_argument("--source", choices=["opus", "hf", "local"], default="opus")
    parser.add_argument("--lang-pair", help="e.g. ja-en, en-vi, ja-vi")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dataset", help="HF dataset name (for --source hf)")
    parser.add_argument("--src", help="Source lang code (for --source hf)")
    parser.add_argument("--tgt", help="Target lang code (for --source hf)")
    parser.add_argument("--all", action="store_true", help="Download all configured pairs")
    parser.add_argument("--merge-domain", action="store_true", help="Merge domain data with upsampling")
    args = parser.parse_args()

    if args.merge_domain:
        load_and_merge_domain_data("data/raw")
        return

    if args.all:
        pairs = [("ja", "en"), ("en", "vi"), ("ja", "vi")]
        for src, tgt in pairs:
            out_dir = LANG_PAIR_DIRS.get(f"{src}-{tgt}", f"data/raw/{src}_{tgt}")
            print(f"\nDownloading {src}→{tgt}...")
            download_from_opus(src, tgt, out_dir, limit=args.limit)
        return

    if args.source == "hf":
        assert args.dataset and args.src and args.tgt, "--dataset, --src, --tgt required for HF source"
        lang_pair = f"{args.src}-{args.tgt}"
        out_dir = LANG_PAIR_DIRS.get(lang_pair, f"data/raw/{args.src}_{args.tgt}")
        download_from_hf_datasets(args.dataset, args.src, args.tgt, out_dir, args.limit)

    elif args.source == "opus":
        assert args.lang_pair, "--lang-pair required for OPUS source"
        src, tgt = args.lang_pair.split("-")
        out_dir = LANG_PAIR_DIRS.get(args.lang_pair, f"data/raw/{src}_{tgt}")
        download_from_opus(src, tgt, out_dir, limit=args.limit)


if __name__ == "__main__":
    main()
