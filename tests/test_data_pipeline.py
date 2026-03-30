"""
tests/test_data_pipeline.py

Unit tests cho data loading, filtering, splitting.
Chạy: pytest tests/test_data_pipeline.py -v
"""

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.prepare_data import (
    filter_pair,
    split_dataset,
    save_jsonl,
    load_tsv_pairs,
    load_jsonl_pairs,
    load_parallel_files,
)


# ─── Filter tests ──────────────────────────────────────────────────────────────

def test_filter_normal_pair():
    assert filter_pair("This is a test", "Đây là một bài kiểm tra") is True


def test_filter_too_short():
    assert filter_pair("Hi", "Xin chào") is False


def test_filter_too_long():
    long_sent = " ".join(["word"] * 200)
    assert filter_pair(long_sent, long_sent) is False


def test_filter_bad_ratio():
    short = "Hello"
    long = " ".join(["word"] * 50)
    assert filter_pair(short, long) is False


def test_filter_all_digits():
    assert filter_pair("12345 67890", "12345 67890") is False


def test_filter_normal_japanese():
    assert filter_pair(
        "会議は午後3時に始まります。",
        "The meeting starts at 3 PM."
    ) is True


# ─── Split tests ──────────────────────────────────────────────────────────────

def test_split_dataset_ratios():
    records = [{"id": i} for i in range(1000)]
    train, valid, test = split_dataset(records, train_ratio=0.9, valid_ratio=0.05)

    assert len(train) == 900
    assert len(valid) == 50
    assert len(test) == 50


def test_split_dataset_no_overlap():
    records = [{"id": i} for i in range(100)]
    train, valid, test = split_dataset(records)

    train_ids = {r["id"] for r in train}
    valid_ids = {r["id"] for r in valid}
    test_ids  = {r["id"] for r in test}

    assert len(train_ids & valid_ids) == 0
    assert len(train_ids & test_ids) == 0
    assert len(valid_ids & test_ids) == 0


def test_split_dataset_covers_all():
    records = [{"id": i} for i in range(200)]
    train, valid, test = split_dataset(records)

    total = len(train) + len(valid) + len(test)
    assert total == 200


# ─── File I/O tests ──────────────────────────────────────────────────────────

def test_save_and_load_jsonl(tmp_path):
    records = [
        {"src": "Hello", "tgt": "Xin chào", "src_lang": "eng_Latn", "tgt_lang": "vie_Latn"},
        {"src": "Goodbye", "tgt": "Tạm biệt", "src_lang": "eng_Latn", "tgt_lang": "vie_Latn"},
    ]
    out = str(tmp_path / "test.jsonl")
    save_jsonl(records, out)

    loaded = []
    with open(out, encoding="utf-8") as f:
        for line in f:
            loaded.append(json.loads(line))

    assert len(loaded) == 2
    assert loaded[0]["src"] == "Hello"
    assert loaded[1]["tgt"] == "Tạm biệt"


def test_load_tsv_pairs(tmp_path):
    tsv_content = "会議は始まります。\tThe meeting starts.\n行きましょう。\tLet's go.\n"
    tsv_file = tmp_path / "pairs.tsv"
    tsv_file.write_text(tsv_content, encoding="utf-8")

    pairs = load_tsv_pairs(str(tsv_file))
    assert len(pairs) == 2
    assert pairs[0] == ("会議は始まります。", "The meeting starts.")
    assert pairs[1] == ("行きましょう。", "Let's go.")


def test_load_jsonl_pairs(tmp_path):
    lines = [
        json.dumps({"src": "Hello", "tgt": "Xin chào"}, ensure_ascii=False),
        json.dumps({"src": "Good morning", "tgt": "Chào buổi sáng"}, ensure_ascii=False),
    ]
    jl_file = tmp_path / "pairs.jsonl"
    jl_file.write_text("\n".join(lines), encoding="utf-8")

    pairs = load_jsonl_pairs(str(jl_file))
    assert len(pairs) == 2
    assert pairs[0] == ("Hello", "Xin chào")


def test_load_parallel_files(tmp_path):
    src_file = tmp_path / "src.txt"
    tgt_file = tmp_path / "tgt.txt"
    src_file.write_text("Line one\nLine two\n", encoding="utf-8")
    tgt_file.write_text("Dòng một\nDòng hai\n", encoding="utf-8")

    pairs = load_parallel_files(str(src_file), str(tgt_file))
    assert len(pairs) == 2
    assert pairs[0] == ("Line one", "Dòng một")
    assert pairs[1] == ("Line two", "Dòng hai")
