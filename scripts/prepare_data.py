"""
scripts/prepare_data.py

Chuẩn bị dataset:
  1. Load raw parallel corpus (JSONL / TSV)
  2. Filter (độ dài, ratio)
  3. Chunk annotation (spaCy)
  4. Split train/valid/test
  5. Save ra data/processed/

Usage:
    python scripts/prepare_data.py --config configs/data_config.yaml
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional

import yaml
from tqdm import tqdm

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chunker import get_chunker, assign_context_weights


# ─── Loaders ──────────────────────────────────────────────────────────────────

def load_tsv_pairs(path: str, src_col: int = 0, tgt_col: int = 1) -> List[Tuple[str, str]]:
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) > max(src_col, tgt_col):
                pairs.append((parts[src_col].strip(), parts[tgt_col].strip()))
    return pairs


def load_jsonl_pairs(path: str, src_key: str = "src", tgt_key: str = "tgt") -> List[Tuple[str, str]]:
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line.strip())
            if src_key in d and tgt_key in d:
                pairs.append((d[src_key], d[tgt_key]))
    return pairs


def load_parallel_files(src_path: str, tgt_path: str) -> List[Tuple[str, str]]:
    srcs = Path(src_path).read_text(encoding="utf-8").strip().splitlines()
    tgts = Path(tgt_path).read_text(encoding="utf-8").strip().splitlines()
    return list(zip(srcs, tgts))


# ─── Filters ─────────────────────────────────────────────────────────────────

def filter_pair(
    src: str,
    tgt: str,
    min_tokens: int = 3,
    max_tokens: int = 128,
    max_ratio: float = 4.5,
) -> bool:
    src_len = len(src.split())
    tgt_len = len(tgt.split())
    if src_len < min_tokens or tgt_len < min_tokens:
        return False
    if src_len > max_tokens or tgt_len > max_tokens:
        return False
    ratio = max(src_len, tgt_len) / (min(src_len, tgt_len) + 1e-6)
    if ratio > max_ratio:
        return False
    # Basic sanity: not all digits/punct
    if re.fullmatch(r"[\d\s\W]+", src) or re.fullmatch(r"[\d\s\W]+", tgt):
        return False
    return True


# ─── Chunk annotation ─────────────────────────────────────────────────────────

def annotate_with_chunks(
    text: str,
    lang: str,
    chunker_cache: dict,
) -> dict:
    """Trả về chunk annotation dict cho 1 câu."""
    lang_short = lang.split("_")[0]  # "jpn_Jpan" → "jpn" → ... map dưới
    LANG_MAP = {
        "jpn": "ja",
        "eng": "en",
        "vie": "vi",
        "ja": "ja",
        "en": "en",
        "vi": "vi",
    }
    lang_key = LANG_MAP.get(lang_short, "en")

    if lang_key not in chunker_cache:
        try:
            chunker_cache[lang_key] = get_chunker(lang_key)
        except Exception as e:
            print(f"[WARN] Could not load chunker for {lang_key}: {e}")
            chunker_cache[lang_key] = None

    chunker = chunker_cache[lang_key]
    if chunker is None:
        return {"chunks": []}

    chunked = chunker.chunk(text)
    chunked = assign_context_weights(chunked)
    return chunked.to_dict()


# ─── Main pipeline ────────────────────────────────────────────────────────────

def process_lang_pair(
    pairs: List[Tuple[str, str]],
    src_lang: str,
    tgt_lang: str,
    config: dict,
    enable_chunks: bool = True,
    chunker_cache: Optional[dict] = None,
) -> List[dict]:
    """
    Xử lý một cặp ngôn ngữ → list of records sẵn sàng cho training.
    """
    if chunker_cache is None:
        chunker_cache = {}

    filter_cfg = config.get("filter", {})
    min_tok = filter_cfg.get("min_tokens", 3)
    max_tok = filter_cfg.get("max_tokens", 128)
    max_ratio = filter_cfg.get("max_length_ratio", 4.5)

    records = []
    skipped = 0

    for src, tgt in tqdm(pairs, desc=f"Processing {src_lang}→{tgt_lang}"):
        if not filter_pair(src, tgt, min_tok, max_tok, max_ratio):
            skipped += 1
            continue

        record = {
            "src": src,
            "tgt": tgt,
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
        }

        if enable_chunks:
            record["src_chunks"] = annotate_with_chunks(src, src_lang, chunker_cache)

        records.append(record)

    print(f"  → Kept {len(records)}, skipped {skipped} pairs")
    return records


def split_dataset(
    records: List[dict],
    train_ratio: float = 0.90,
    valid_ratio: float = 0.05,
    seed: int = 42,
) -> Tuple[List[dict], List[dict], List[dict]]:
    random.seed(seed)
    random.shuffle(records)
    n = len(records)
    train_end = int(n * train_ratio)
    valid_end = train_end + int(n * valid_ratio)
    return records[:train_end], records[train_end:valid_end], records[valid_end:]


def save_jsonl(records: List[dict], path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Saved {len(records)} records → {path}")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prepare NLLB training data")
    parser.add_argument("--config", default="configs/data_config.yaml")
    parser.add_argument("--no-chunks", action="store_true", help="Skip chunk annotation (faster)")
    parser.add_argument("--limit", type=int, default=None, help="Limit pairs per lang pair (debug)")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    data_cfg = config["data"]
    raw_dir = Path(data_cfg["raw_dir"])
    processed_dir = Path(data_cfg["processed_dir"])
    splits_cfg = data_cfg["splits"]
    enable_chunks = data_cfg.get("chunker", {}).get("enabled", True) and not args.no_chunks

    all_train, all_valid, all_test = [], [], []
    chunker_cache = {}

    for pair in data_cfg["language_pairs"]:
        src_lang = pair["src"]
        tgt_lang = pair["tgt"]
        pair_dir = raw_dir / pair["dir"]

        if not pair_dir.exists():
            print(f"[SKIP] {pair_dir} does not exist. Run scripts/download_data.py first.")
            continue

        print(f"\n{'='*50}")
        print(f"Processing: {src_lang} → {tgt_lang} ({pair_dir})")

        # Try loading different formats
        pairs = []
        tsv_file = pair_dir / "pairs.tsv"
        jsonl_file = pair_dir / "pairs.jsonl"
        src_file = pair_dir / "src.txt"
        tgt_file = pair_dir / "tgt.txt"

        if tsv_file.exists():
            pairs = load_tsv_pairs(str(tsv_file))
        elif jsonl_file.exists():
            pairs = load_jsonl_pairs(str(jsonl_file))
        elif src_file.exists() and tgt_file.exists():
            pairs = load_parallel_files(str(src_file), str(tgt_file))
        else:
            print(f"[SKIP] No data file found in {pair_dir}")
            continue

        if args.limit:
            pairs = pairs[:args.limit]

        records = process_lang_pair(
            pairs, src_lang, tgt_lang, data_cfg,
            enable_chunks=enable_chunks,
            chunker_cache=chunker_cache,
        )

        train, valid, test = split_dataset(
            records,
            splits_cfg["train"],
            splits_cfg["validation"],
        )
        all_train.extend(train)
        all_valid.extend(valid)
        all_test.extend(test)

    # Shuffle merged datasets
    random.shuffle(all_train)
    random.shuffle(all_valid)
    random.shuffle(all_test)

    print(f"\n{'='*50}")
    print(f"Total: train={len(all_train)}, valid={len(all_valid)}, test={len(all_test)}")

    save_jsonl(all_train, str(processed_dir / "train.jsonl"))
    save_jsonl(all_valid, str(processed_dir / "valid.jsonl"))
    save_jsonl(all_test,  str(processed_dir / "test.jsonl"))

    print("\nData preparation complete! ✅")


if __name__ == "__main__":
    main()
