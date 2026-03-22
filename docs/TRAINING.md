# 🏋️ Training Guide — NLLB Contextual Fine-tuning

## Tổng quan pipeline

```
raw corpus → filter → chunk annotate → tokenize → fine-tune → evaluate
```

## Yêu cầu phần cứng

| Config | GPU VRAM | Thời gian/epoch (100K pairs) |
|---|---|---|
| Minimal (batch=4, grad_accum=8) | 8 GB | ~3h |
| Recommended (batch=16, grad_accum=4) | 16 GB | ~1h |
| Fast (batch=32, fp16) | 24 GB | ~30min |
| Multi-GPU (DDP) | 2×16 GB | ~25min |

## Chunk-aware loss

### Cách hoạt động

Mỗi token trong target sequence được gán weight dựa trên chunk mà nó thuộc về:

```
sentence: "The meeting starts at 3 PM"
chunks:
  - "The meeting"  → NP, subj  → weight 0.95
  - "starts"       → VP, root  → weight 1.00
  - "at 3 PM"      → PP, prep  → weight 0.70

token-level weights (target side):
  [The=0.95, meeting=0.95, starts=1.00, at=0.70, 3=0.70, PM=0.70]

loss = λ * sentence_CE_loss + (1-λ) * weighted_CE_loss
```

Tham số `chunk_loss_weight` (λ) trong `train_config.yaml`:
- `0.0` = disable (standard NLLB loss)
- `0.3` = 70% standard + 30% chunk-weighted ← **khuyến nghị**
- `1.0` = thuần chunk-weighted

### Kết quả thực nghiệm (dự kiến)

| Config | BLEU (ja→vi) | chrF |
|---|---|---|
| NLLB-600M baseline | ~18 | ~42 |
| Fine-tuned, no chunk loss | ~24 | ~51 |
| Fine-tuned + chunk loss λ=0.3 | ~26 | ~54 |

## Training từng bước

### Bước 1: Chuẩn bị data

```bash
# Download OPUS corpus (~500K pairs ja↔en + en↔vi)
make download-data

# Filter + split (train/valid/test)
make prepare

# Thêm chunk annotation
make annotate
```

Sau bước này `data/processed/` sẽ có:
- `train.jsonl` — ~450K records
- `valid.jsonl` — ~25K records
- `test.jsonl`  — ~25K records

### Bước 2: Download base model

```bash
make download-model
# → models/pretrained/facebook_nllb-200-distilled-600M/
```

### Bước 3: Chạy training

```bash
make train
# Hoặc với custom args:
python scripts/train.py \
  --config configs/train_config.yaml \
  --epochs 5 \
  --lr 3e-5 \
  --chunk-loss-weight 0.3
```

TensorBoard logs: `tensorboard --logdir models/finetuned/runs`

### Bước 4: Evaluate

```bash
make evaluate
# → eval_ja_vi.json (BLEU, chrF, TER scores)
```

### Bước 5: Inference

```bash
# Single sentence
python scripts/translate.py --text "会議は午後3時です。" --src ja --tgt vi --debug

# File batch
python scripts/translate.py \
  --src-file input.txt --out output.txt \
  --src ja --tgt vi \
  --model models/finetuned/best
```

## Hyperparameter tuning

Các tham số quan trọng nhất cần tune:

| Parameter | Default | Range để thử |
|---|---|---|
| `learning_rate` | 5e-5 | 1e-5 ... 1e-4 |
| `chunk_loss_weight` | 0.3 | 0.1, 0.2, 0.3, 0.5 |
| `num_beams` (eval) | 4 | 2, 4, 5 |
| `max_input_length` | 256 | 128, 256 |
| `warmup_ratio` | 0.05 | 0.03, 0.05, 0.1 |

## LoRA fine-tuning (khi VRAM < 16GB)

Bật LoRA trong `train_config.yaml`:

```yaml
peft:
  enabled: true
  method: lora
  r: 16
  lora_alpha: 32
  target_modules:
    - q_proj
    - v_proj
```

LoRA giảm trainable params từ ~600M → ~5M, VRAM từ 16GB → ~6GB.

## Multi-GPU (DDP)

```bash
torchrun --nproc_per_node=2 scripts/train.py --config configs/train_config.yaml
```

## Tips thực tế

1. **Domain data quan trọng**: 3000 câu IT/meeting domain × 3 (upsample) có thể tăng BLEU trên domain-specific test set hơn 5 điểm.

2. **JA→VI ít data hơn**: Nên dùng JA→EN→VI pivot (2 bước dịch) để tăng chất lượng trên cặp JA→VI.

3. **Context window**: Setting `context_window: 2` trong chunk config sẽ ghép 2 câu trước/sau làm context khi train → tốt cho hội thoại liên tiếp.

4. **Early stopping**: Mặc định patience=3 epoch. Với NLLB thường đạt plateau sau epoch 3-4.
