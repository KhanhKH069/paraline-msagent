# 🌐 NLLB Contextual Trainer — JA / EN / VI

> **Sub-project của Paraline MSAgent** — Fine-tune NLLB-200 với pipeline chunk-aware contextual translation cho 3 ngôn ngữ Nhật · Anh · Việt.

---

## Ý tưởng cốt lõi: Chunk-Aware Contextual Translation

```
Input câu dài
       │
       ▼
┌─────────────────┐
│  Chunker (spaCy) │  ← Phân tách: NP, VP, PP, SubClause
└────────┬─────────┘
         │  [chunk_1, chunk_2, ..., chunk_n]
         ▼
┌──────────────────────┐
│  Context Embedder     │  ← Mỗi chunk lấy embedding từ câu đầy đủ
│  (NLLB encoder)      │     (cross-attention với toàn bộ context)
└────────┬─────────────┘
         │  [ctx_vec_1, ctx_vec_2, ..., ctx_vec_n]
         ▼
┌──────────────────────┐
│  Chunk Translator     │  ← Dịch từng chunk với context awareness
│  (NLLB decoder)      │     + positional weighting
└────────┬─────────────┘
         │  [trans_chunk_1, ..., trans_chunk_n]
         ▼
┌──────────────────────┐
│  Sentence Assembler   │  ← Ghép lại, xử lý boundary, fluency check
└────────┬─────────────┘
         ▼
     Output câu dịch hoàn chỉnh
```

## Cấu trúc dự án

```
nllb-trainer/
├── data/
│   ├── raw/               # Dataset gốc (parallel corpus JA/EN/VI)
│   │   ├── ja_en/         # Cặp Nhật–Anh
│   │   ├── en_vi/         # Cặp Anh–Việt
│   │   ├── ja_vi/         # Cặp Nhật–Việt (tổng hợp)
│   │   └── vocab/         # TSV chứa từ vựng chuyên ngành (IT, business)
│   ├── processed/         # Sau tokenize + chunk annotation
│   └── augmented/         # Back-translation augmentation
├── src/
│   ├── chunker/           # Phân đoạn câu theo ngữ pháp
│   ├── tokenizer/         # Wrap sentencepiece NLLB tokenizer
│   ├── trainer/           # Fine-tuning logic (HuggingFace Trainer)
│   ├── evaluator/         # BLEU / chrF / TER scoring
│   └── utils/             # Helpers, logging, config
├── configs/               # YAML training configs
├── scripts/               # CLI scripts: download, preprocess, train, eval
├── notebooks/             # Jupyter: data analysis + demo
├── models/                # Model checkpoints
├── tests/                 # Unit + integration tests
└── docs/                  # Kỹ thuật chi tiết
```

## Quick Start

```bash
# 1. Cài môi trường
uv sync
uv run python -m spacy download ja_core_news_sm
uv run python -m spacy download en_core_web_sm

# 2. Download base model
uv run python scripts/download_model.py --model facebook/nllb-200-distilled-600M

# 3. Tiêm từ vựng chuyên ngành (vocab injection)
uv run python scripts/inject_vocab.py

# 4. Chuẩn bị dữ liệu
uv run python scripts/prepare_data.py --config configs/data_config.yaml

# 5. Chunk annotation
uv run python scripts/annotate_chunks.py --overwrite

# 6. Train
uv run python scripts/train.py --config configs/train_config.yaml

# 7. Evaluate
uv run python scripts/evaluate.py --checkpoint models/finetuned/best --test-set data/processed/test
```

## Ngôn ngữ codes (NLLB-200 Flores)

| Ngôn ngữ | NLLB Code |
|---|---|
| Tiếng Nhật | `jpn_Jpan` |
| Tiếng Anh  | `eng_Latn` |
| Tiếng Việt | `vie_Latn` |

## Dataset

Chi tiết xem `data/README.md`. Tổng hợp từ:
- **JW300** (ja↔en, en↔vi)
- **OPUS-100** parallel corpus
- **CCAligned** (en↔vi)
- **Custom business vocab** (IT/meeting domain từ VMG)

## Training Pipeline

Chi tiết xem `docs/TRAINING.md`.
