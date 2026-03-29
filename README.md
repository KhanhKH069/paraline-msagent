# 🎙️ Vietnamese Bert-VITS2 — Text-to-Speech

Hệ thống TTS tiếng Việt dựa trên **VITS2** kết hợp **PhoBERT** để tổng hợp giọng nói tự nhiên, có ngữ điệu và cảm xúc.

## ✨ Tính năng

- **PhoBERT** semantic embeddings — hiểu ngữ cảnh tiếng Việt sâu
- **VnCoreNLP + G2P** — tách từ và chuyển đổi âm vị chính xác
- **6 thanh điệu** tiếng Việt được xử lý đầy đủ
- **Stochastic Duration Predictor** với adversarial learning (VITS2)
- **Normalizing Flows + Transformer Block** — long-term dependency
- **HiFi-GAN Decoder** — chất lượng audio 22050 Hz
- Multi-speaker hỗ trợ nhiều giọng đọc

## 📁 Cấu trúc thư mục

```
vits2/
├── configs/                  # Cấu hình training và inference
│   ├── base_vi.json          # Config cơ bản tiếng Việt
│   └── multi_speaker.json    # Config multi-speaker
├── data/
│   ├── raw_audio/            # Audio gốc (chưa xử lý)
│   ├── sliced_audio/         # Audio đã cắt (2–10s)
│   └── transcripts/          # Nhãn văn bản gốc
├── dataset/
│   ├── list.txt              # Danh sách: wav|transcript|speaker_id
│   ├── train.txt             # Split training
│   └── val.txt               # Split validation
├── text/
│   ├── cleaners/             # Text normalization tiếng Việt
│   └── phoneme/              # G2P và bảng âm vị
├── models/
│   ├── bert_vits2.py         # Kiến trúc model chính
│   ├── duration_predictor.py # Stochastic duration predictor
│   ├── normalizing_flows.py  # Flows + transformer block
│   ├── text_encoder.py       # Speaker-conditioned text encoder
│   └── hifigan.py            # HiFi-GAN decoder
├── speakers/                 # Quản lý thông tin và embedding từng giọng
│   ├── speaker_registry.py   # Registry để quản lý ID và metadata
│   ├── speaker_encoder.py    # Trích xuất speaker embedding với Resemblyzer
│   ├── speakers.json         # Danh sách giọng đọc đã đăng ký
│   └── embeddings/           # Thư mục chứa file embedding (.pt)
├── training/
│   ├── train.py              # Script training chính
│   ├── trainer.py            # Training loop
│   └── losses.py             # Các hàm loss
├── inference/
│   ├── infer.py              # Inference đơn lẻ
│   ├── batch_infer.py        # Inference theo batch
│   └── multi_infer.py        # Inference chọn giọng (cho multi-speaker)
├── utils/
│   ├── audio.py              # Xử lý audio
│   ├── data_utils.py         # Dataset loader
│   ├── mel_processing.py     # Mel-spectrogram
│   └── speaker_utils.py      # Các hàm trợ giúp xử lý speaker
├── scripts/
│   ├── prepare_dataset.py    # Pipeline chuẩn bị dataset
│   ├── slice_audio.py        # Tự động cắt audio
│   ├── normalize_text.py     # Chuẩn hóa văn bản
│   ├── compute_statistics.py # Thống kê dataset
│   ├── add_speaker.py        # Thêm giọng mới vào model
│   └── export_speaker_embed.py # Trích xuất embedding từ audio
├── checkpoints/              # Model checkpoints
├── logs/                     # TensorBoard logs
├── outputs/                  # Audio output khi inference
├── requirements.txt
└── setup.py
```

## 🚀 Hướng dẫn nhanh

### 1. Cài đặt môi trường

```bash
conda create -n vits2-vi python=3.10
conda activate vits2-vi
pip install -r requirements.txt
```

### 2. Chuẩn bị Dataset

Bạn có hai cách để chuẩn bị dữ liệu:

**Cách A: Dùng hình thức tự động (Synthetic Data bằng gTTS)**
Thích hợp để chạy thử hoặc pre-train với lượng dữ liệu lớn mà không cần thu âm:
```bash
# Tạo ~600+ câu tiếng Việt (đã đi kèm sẵn) thành Audio chuẩn 22050Hz (yêu cầu FFmpeg)
uv run python scripts/generate_synthetic.py --output_dir data/synthetic_audio --workers 4
```
*(Script này tự động sinh file WAV, chia tập train/val và tạo `dataset/list.txt`)*

**Cách B: Dùng audio có sẵn**
Thích hợp nếu bạn có bộ thu âm thực tế chất lượng cao:
```bash
# Cắt audio thành clip 2–10 giây
uv run python scripts/slice_audio.py --input data/raw_audio/ --output data/sliced_audio/

# Chuẩn hóa văn bản nhãn, tạo list.txt
uv run python scripts/normalize_text.py --input data/transcripts/ --output dataset/list.txt
```

### 3. Training

Sau khi có `dataset/list.txt`, `train.txt` và `val.txt`, bắt đầu quá trình huấn luyện:

**Training một giọng (Single Speaker)**
```bash
uv run python training/train.py --config configs/base_vi.json
```

**Training nhiều giọng (Multi-speaker)**

Đầu tiên, thêm giọng đọc mới:
```bash
uv run python scripts/add_speaker.py --name "giong_moi" --audio_sample data/raw_audio/sample.wav
```
Sau đó, chạy training:
```bash
uv run python training/train.py --config configs/multi_speaker.json
```

### 4. Inference

**Inference với một giọng:**
```bash
python inference/infer.py \
  --text "Xin chào, tôi là trợ lý giọng nói tiếng Việt." \
  --checkpoint checkpoints/G_100000.pth \
  --output outputs/hello.wav
```

**Inference chọn giọng (Multi-speaker):**
```bash
python inference/multi_infer.py \
  --text "Xin chào, đây là giọng nữ miền Bắc." \
  --speaker "nu_bac" \
  --checkpoint checkpoints/multi_G_100000.pth \
  --output outputs/multi_hello.wav
```

### 5. Khởi chạy API Server

Dự án cung cấp một FastAPI server qua `main.py` để sử dụng TTS thông qua giao diện HTTP REST API.

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Sau khi khởi chạy, bạn có thể:
- Truy cập tài liệu giao diện Swagger UI tại: `http://127.0.0.1:8000/docs`.
- Gửi yêu cầu qua `curl` (với nội dung dạng JSON):

```bash
curl -X POST "http://127.0.0.1:8000/tts" \
     -H "Content-Type: application/json" \
     -d '{
           "text": "Xin chào, tôi là trợ lý giọng nói tiếng Việt.",
           "speaker_id": 0,
           "checkpoint_path": "checkpoints/G_100000.pth",
           "config_path": "configs/base_vi.json"
         }' --output result.wav
```

## 📊 Yêu cầu Dataset

| Thông số | Giá trị |
|----------|---------|
| Tổng thời lượng | 1–2 giờ (single speaker) |
| Định dạng | WAV, Mono, 22050 Hz |
| Độ dài mỗi clip | 2–10 giây |
| Tạp âm | Không có (SNR > 35 dB) |
| Reverb/Echo | Không có |
| Số lượng clips | ~2000–5000 clips |

## 🔧 Yêu cầu phần cứng

- **Training**: 4× NVIDIA V100/A100 (hoặc 1× A100 với batch nhỏ hơn)
- **Inference**: 1× GPU bất kỳ (hoặc CPU, chậm hơn)
- **RAM**: ≥ 32 GB
- **Disk**: ≥ 50 GB cho checkpoints

## 📖 Tài liệu tham khảo

- [VITS2 Paper](https://arxiv.org/abs/2307.16430) — Kong et al., SK Telecom 2023
- [PhoBERT](https://github.com/VinAIResearch/PhoBERT) — VinAI Research
- [VnCoreNLP](https://github.com/vncorenlp/VnCoreNLP) — NLP toolkit tiếng Việt
