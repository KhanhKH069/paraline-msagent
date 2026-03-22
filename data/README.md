# 📚 NLLB Training Database — JA / EN / VI

## Cấu trúc thư mục

```
data/
├── raw/
│   ├── ja_en/          # Nhật ↔ Anh parallel corpus
│   │   ├── pairs.tsv   # tab-separated: ja \t en
│   │   ├── src.txt     # câu Nhật (1 câu/dòng)
│   │   └── tgt.txt     # câu Anh (1 câu/dòng)
│   │
│   ├── en_vi/          # Anh ↔ Việt parallel corpus
│   │   ├── pairs.tsv
│   │   ├── src.txt
│   │   └── tgt.txt
│   │
│   ├── ja_vi/          # Nhật ↔ Việt (pivot hoặc direct)
│   │   ├── pairs.tsv
│   │   ├── src.txt
│   │   └── tgt.txt
│   │
│   ├── vocab/          # Domain vocabulary (IT/meeting/business)
│   │   ├── it_terms_ja_en_vi.tsv
│   │   ├── meeting_phrases_ja_en_vi.tsv
│   │   └── business_ja_en_vi.tsv
│   │
│   └── domain/         # Domain-specific corpus (VMG use-case)
│       ├── tech_support/
│       ├── meeting_transcripts/
│       └── business_email/
│
├── processed/          # Sau prepare_data.py
│   ├── train.jsonl     # ~90% của tổng dataset
│   ├── valid.jsonl     # ~5%
│   └── test.jsonl      # ~5%
│
└── augmented/          # Back-translation augmentation
    └── back_trans.jsonl
```

## Format JSONL (processed)

```json
{
  "src": "会議は午後3時に始まります。",
  "tgt": "Cuộc họp bắt đầu lúc 3 giờ chiều.",
  "src_lang": "jpn_Jpan",
  "tgt_lang": "vie_Latn",
  "src_chunks": {
    "original": "会議は午後3時に始まります。",
    "lang": "ja",
    "tokens": ["会議", "は", "午後", "3", "時", "に", "始まり", "ます", "。"],
    "chunks": [
      {
        "text": "会議は",
        "type": "NP",
        "start": 0,
        "end": 2,
        "position_ratio": 0.0,
        "dep_role": "subj",
        "head": "会議",
        "context_weight": 0.95
      },
      {
        "text": "午後3時に",
        "type": "PP",
        "start": 2,
        "end": 6,
        "position_ratio": 0.25,
        "dep_role": "prep",
        "head": "時",
        "context_weight": 0.70
      },
      {
        "text": "始まります",
        "type": "VP",
        "start": 6,
        "end": 8,
        "position_ratio": 0.67,
        "dep_role": "root",
        "head": "始まり",
        "context_weight": 1.0
      }
    ]
  }
}
```

## Nguồn dữ liệu khuyến nghị

### JA ↔ EN
| Dataset | Pairs | Source |
|---|---|---|
| JParaCrawl v3 | ~25M | jparacrawl.org |
| JESC | 3.2M | nlp.stanford.edu |
| Tatoeba (ja-en) | ~250K | opus.nlpl.eu |
| KFTT (Kyoto Free Translation) | 440K | kftt.ar.cs.cmu.edu |
| TED Talks (ja-en) | ~200K | opus.nlpl.eu |

### EN ↔ VI
| Dataset | Pairs | Source |
|---|---|---|
| CCAligned (en-vi) | ~800K | opus.nlpl.eu |
| OpenSubtitles (en-vi) | ~3M | opus.nlpl.eu |
| Tatoeba (en-vi) | ~20K | opus.nlpl.eu |
| WikiMatrix (en-vi) | ~120K | opus.nlpl.eu |
| OPUS-100 (en-vi) | ~100K | opus.nlpl.eu |

### JA ↔ VI (ít nguồn trực tiếp hơn)
| Dataset | Pairs | Source |
|---|---|---|
| Tatoeba (ja-vi) | ~5K | opus.nlpl.eu |
| WikiMatrix (ja-vi) | ~50K | opus.nlpl.eu |
| JESC pivot (ja→en→vi) | synthesized | - |

## Download nhanh với script

```bash
# Download từ OPUS
python scripts/download_data.py --source opus --lang-pair ja-en --limit 500000
python scripts/download_data.py --source opus --lang-pair en-vi --limit 500000
python scripts/download_data.py --source opus --lang-pair ja-vi --limit 50000

# Hoặc dùng Makefile
make download-data
```

## Domain vocabulary (IT/Meeting)

File `data/raw/vocab/` chứa thuật ngữ chuyên ngành đã được dịch sẵn 3 chiều.
Dùng để augment corpus và làm constrained vocabulary trong training.

Domain được ưu tiên cho VMG use-case:
- IT/Software: API, server, deploy, bug, release, sprint...
- Meeting: agenda, minutes, action items, follow-up...
- Business: contract, invoice, deadline, proposal...
