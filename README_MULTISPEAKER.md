# 🎭 Multi-Speaker Addon — Vietnamese Bert-VITS2

Bộ file bổ sung để hỗ trợ nhiều giọng đọc khác nhau trong cùng một model.

## 📁 Thả file vào project như sau:

```
vits2/                          ← project gốc của bạn
├── speakers/                   ← NEW: quản lý thông tin từng giọng
│   ├── speaker_registry.py
│   ├── speaker_encoder.py
│   └── speakers.json           ← danh sách giọng đọc
├── scripts/
│   ├── add_speaker.py          ← NEW: thêm giọng mới vào model
│   └── export_speaker_embed.py ← NEW: trích xuất embedding từ audio
├── inference/
│   └── multi_infer.py          ← NEW: inference chọn giọng
├── utils/
│   └── speaker_utils.py        ← NEW: helper functions
└── configs/
    └── multi_speaker.json      ← đã có sẵn, cập nhật lại
```

## 🚀 Quy trình thêm giọng mới

```bash
# Bước 1: Đăng ký giọng mới + trích xuất embedding từ ~30s audio mẫu
python scripts/add_speaker.py \
    --name "nu_bac" \
    --audio_sample data/raw_audio/nu_bac_sample.wav \
    --speaker_id 3

# Bước 2: Fine-tune model với giọng mới (cần ~30 phút audio)
python training/train.py \
    --config configs/multi_speaker.json \
    --resume checkpoints/G_300000.pth

# Bước 3: Inference chọn giọng
python inference/multi_infer.py \
    --text "Xin chào, đây là giọng nữ miền Bắc." \
    --speaker "nu_bac" \
    --checkpoint checkpoints/G_350000.pth
```
