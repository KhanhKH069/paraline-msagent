# ⚡ Quick Start — Vietnamese Bert-VITS2

## 1. Cài đặt

```bash
conda create -n vits2-vi python=3.10 -y
conda activate vits2-vi

# Cài PyTorch (chọn đúng CUDA version của bạn)
pip install torch==2.1.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118

# Cài các thư viện còn lại
pip install -r requirements.txt
```

## 2. Chuẩn bị dữ liệu

### Cấu trúc thư mục cần có:
```
data/
├── raw_audio/          ← Đặt file audio gốc (.wav, .mp3, .flac) vào đây
└── transcripts/        ← Tạo file .txt cùng tên với audio
    ├── clip_00001.txt  ← Nội dung: "xin chào hôm nay tôi rất vui"
    └── clip_00002.txt
```

### Chạy pipeline chuẩn bị:
```bash
# Tự động: cắt audio + validate + tạo list.txt
python scripts/prepare_dataset.py \
    --input data/raw_audio/ \
    --transcripts data/transcripts/ \
    --speaker 0

# Kiểm tra thống kê:
python scripts/compute_statistics.py --dataset dataset/list.txt
```

## 3. Training

### Single GPU (1 Giọng):
```bash
python training/train.py --config configs/base_vi.json
```

### Multi GPU (1 Giọng, 4× GPUs):
```bash
python training/train.py --config configs/base_vi.json --n_gpus 4
```

### Multi-speaker Training:
1. Trích xuất embedding và đăng ký giọng đọc:
```bash
python scripts/add_speaker.py --name "ten_giong_doc" --audio_sample data/raw_audio/file_mau.wav
```
2. Chạy training:
```bash
python training/train.py --config configs/multi_speaker.json
```

### Theo dõi bằng TensorBoard:
```bash
tensorboard --logdir logs/
```

## 4. Inference

```bash
# Một câu đơn lẻ (Single Speaker)
python inference/infer.py \
    --text "Xin chào, tôi là trợ lý giọng nói tiếng Việt." \
    --checkpoint checkpoints/G_100000.pth \
    --output outputs/hello.wav

# Multi-speaker Inference
python inference/multi_infer.py \
    --text "Chào bạn, đây là giọng đọc tùy chỉnh." \
    --speaker "ten_giong_doc" \
    --checkpoint checkpoints/G_100000.pth

# Nhiều câu từ file
python inference/batch_infer.py \
    --input data/sample_sentences.txt \
    --checkpoint checkpoints/G_100000.pth \
    --output_dir outputs/batch/
```

## 5. Test nhanh các module

```bash
# Test text normalization
python text/cleaners/vietnamese_cleaners.py

# Test G2P
python text/phoneme/vi_g2p.py

# Test dataset preparation (dry run)
python scripts/prepare_dataset.py \
    --input data/raw_audio/ \
    --transcripts data/transcripts/ \
    --stats_only
```

## ⚠️ Lưu ý quan trọng

| Vấn đề | Giải pháp |
|--------|-----------|
| OOM (Out of Memory) | Giảm `batch_size` trong config |
| Audio có reverb | Dùng phần mềm deReverb trước khi train |
| Text normalization sai | Sửa ABBREVIATIONS_VI trong `text/cleaners/vietnamese_cleaners.py` |
| Training quá chậm | Bật `fp16_run: true` trong config |
| Giọng bị vấp | Tăng `length_scale` lúc inference (VD: 1.1) |
| Âm thanh bị méo | Kiểm tra `noise_scale` — thử giảm xuống 0.5 |

## 📊 Thời gian training ước tính

| GPU | Batch Size | Steps đến chất lượng tốt | Thời gian |
|-----|-----------|--------------------------|-----------|
| 1× A100 80GB | 32 | ~300k steps | ~3 ngày |
| 4× A100 | 32 | ~300k steps | ~18 giờ |
| 1× V100 32GB | 16 | ~300k steps | ~5 ngày |
| 1× RTX 3090 | 8 | ~300k steps | ~6 ngày |
