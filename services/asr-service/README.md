# ASR Service — Vietnamese Speech Recognition

Microservice tích hợp Gipformer vào kiến trúc Paraline. Nhận diện giọng nói tiếng Việt từ file audio hoặc video qua HTTP API.

## Stack

- **Model**: [gipformer-65M-rnnt](https://huggingface.co/g-group-ai-lab/gipformer-65M-rnnt) (Zipformer Transducer)
- **Runtime**: [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (CPU / GPU)
- **Framework**: FastAPI + Uvicorn
- **Port mặc định**: `8005`

## Cài đặt

```bash
cd services/asr-service
pip install -r requirements.txt

# ffmpeg (bắt buộc cho transcribe/video):
#   Windows : winget install ffmpeg
#   Ubuntu  : sudo apt install ffmpeg
#   macOS   : brew install ffmpeg

# (Tuỳ chọn) Dịch tự động sang EN/JA:
pip install deep-translator
```

## Chạy locally

```bash
cd services/asr-service
python main.py

# Với quantize INT8 (nhẹ hơn, nhanh hơn):
ASR_QUANTIZE=int8 python main.py

# Với tự động dịch:
ASR_TRANSLATE=true python main.py
```

## Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| `POST` | `/transcribe/file` | Upload file audio (WAV, FLAC, OGG, MP3, M4A) |
| `POST` | `/transcribe/video` | Upload file video (MP4, MKV, AVI, MOV, WEBM…) |
| `GET` | `/health` | Health check |

### `POST /transcribe/file`

```bash
curl -X POST http://localhost:8005/transcribe/file \
     -F "file=@audio.wav" \
     -F "translate=false"
```

**Response:**
```json
{
  "transcript": "xin chào thế giới",
  "audio_duration_s": 2.345,
  "latency_ms": 312.5,
  "rtf": 0.133
}
```

Với `?translate=true`:
```json
{
  "transcript": "xin chào thế giới",
  "translations": { "en": "hello world", "ja": "こんにちは世界" },
  "audio_duration_s": 2.345,
  "latency_ms": 1012.3,
  "rtf": 0.431
}
```

### `POST /transcribe/video`

```bash
curl -X POST http://localhost:8005/transcribe/video \
     -F "file=@meeting.mp4"
```

**Response** (bổ sung thêm `extract_latency_ms` và `asr_latency_ms`):
```json
{
  "transcript": "...",
  "audio_duration_s": 120.0,
  "latency_ms": 8320.0,
  "rtf": 0.069,
  "extract_latency_ms": 2100.0,
  "asr_latency_ms": 6220.0
}
```

### `GET /health`

```bash
curl http://localhost:8005/health
```

```json
{
  "status": "ok",
  "service": "asr-service",
  "model": "gipformer-65M-rnnt",
  "quantize": "fp32",
  "num_threads": 4,
  "translator_available": false
}
```

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|---------|-------|
| `ASR_QUANTIZE` | `fp32` | Độ chính xác model: `fp32` hoặc `int8` |
| `ASR_NUM_THREADS` | `4` | Số luồng CPU |
| `ASR_HOST` | `0.0.0.0` | Bind host |
| `ASR_PORT` | `8005` | Bind port |
| `ASR_TRANSLATE` | `false` | Tự động dịch mọi request |

## Chạy với Docker

```bash
docker build -t paraline-asr-service .
docker run -p 8005:8005 paraline-asr-service
```

## CLI Tools (gipformer/)

Các script CLI gốc vẫn nằm trong `gipformer/` và có thể dùng trực tiếp:

```bash
# Nhận diện realtime từ mic hoặc Stereo Mix
python gipformer/infer_mic.py --list-devices
python gipformer/infer_mic.py --device 3 --translate

# Nhận diện từ file audio
python gipformer/infer_onnx.py --audio audio.wav

# Nhận diện từ video
python gipformer/infer_video.py --video meeting.mp4
```

## Cấu trúc

```
services/asr-service/
├── core/
│   ├── __init__.py
│   ├── recognizer.py   ← sherpa-onnx engine
│   ├── video.py        ← ffmpeg audio extraction
│   └── translator.py   ← VI → EN/JA (deep-translator)
├── main.py             ← FastAPI app
├── requirements.txt
├── Dockerfile
└── README.md
```
