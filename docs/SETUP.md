# Paraline MSAgent — Hướng dẫn Cài đặt & Vận hành

## Yêu cầu phần cứng

### VMG AI Server
| Component | Minimum | Recommended |
|---|---|---|
| CPU | 8 cores | 16 cores |
| RAM | 32 GB | 64 GB |
| GPU | NVIDIA 8GB VRAM | NVIDIA RTX 3090 / A4000 (24GB) |
| Disk | 100 GB SSD | 250 GB NVMe |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Network | VMG_STAFF LAN (1Gbps) | VMG_STAFF LAN (1Gbps) |

> **Note về GPU VRAM:**
> - Whisper large-v3: ~6 GB
> - NLLB-200 600M: ~2.5 GB (CPU OK)
> - Ollama Llama 3 8B: ~6 GB
> - Tổng (full stack GPU): ~14.5 GB → cần RTX 3090 / A4000

### Client App (máy nhân viên)
- Windows 10/11 64-bit
- RAM: 4 GB trở lên (app chiếm ~300MB)
- Python 3.10+
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) đã cài đặt

---

## Cài đặt Server

### Bước 1: Cài Docker & NVIDIA Container Toolkit
```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

### Bước 2: Clone & cấu hình
```bash
git clone <repo-url> paraline-msagent
cd paraline-msagent

cp .env.example .env
nano .env   # Sửa: VMG_SERVER_IP, ADMIN_API_TOKEN, CLIENT_API_KEY, ...
```

### Bước 3: Download AI models
```bash
# Cài Python dependencies để chạy downloader
pip install faster-whisper transformers sentencepiece

make download-models
# Sẽ download: Whisper large-v3, NLLB-200, Piper vi_VN, NotoSansCJK font
# Thời gian: ~30-60 phút tùy internet
```

### Bước 4: Khởi động
```bash
make all        # build images + start containers
make health     # kiểm tra tất cả services
make pull-llm   # download Llama 3 8B (sau khi ollama container chạy)
```

### Bước 5: Kiểm tra
```bash
# Test Whisper
curl -X POST http://localhost:8001/health

# Test Translation
curl -X POST http://localhost:8002/translate \
  -H "Content-Type: application/json" \
  -d '{"text":"こんにちは","src_lang":"jpn_Jpan","tgt_lang":"vie_Latn"}'
# Expected: {"translated_text":"Xin chào", ...}

# Swagger UI
open http://localhost:8056/docs
```

---

## Cài đặt Client App (Windows)

### Bước 1: Cài VB-Audio Virtual Cable
1. Download từ https://vb-audio.com/Cable/
2. Cài đặt → Restart máy
3. Vào `Sound Settings` → đảm bảo thấy thiết bị `CABLE Input / CABLE Output`
4. Trong **Google Meet** (hoặc Chrome) → chọn **Speaker** là `CABLE Input` để app bắt được audio cuộc họp (inbound).

### Bước 2: Cài Python dependencies
```powershell
cd paraline-msagent/client
pip install -r requirements.txt
```

> Lưu ý quan trọng:
> - **Chỉ cài dependencies trong `client/requirements.txt` trên Windows.**
> - Các thư mục `services/*` là **server microservices** và được chạy bằng **Docker Compose** (Linux containers).  
>   Không chạy kiểu “cài tất cả `requirements.txt` trong repo” trên Windows vì sẽ kéo theo các package server (ví dụ `faster-whisper`/`av`, `paddlepaddle`) dễ lỗi build/wheel.
>
> Nếu bạn gặp lỗi kiểu `No module named pip` trong virtualenv:
> ```powershell
> # tạo lại venv có pip
> py -3.11 -m venv .venv
> .\.venv\Scripts\python -m ensurepip --upgrade
> .\.venv\Scripts\python -m pip install --upgrade pip
> 
> # cài deps cho client
> cd .\client
> ..\.venv\Scripts\python -m pip install -r requirements.txt
> ```

### Bước 3: Cấu hình
```powershell
# Set environment variables (hoặc tạo client/.env)
$env:PARALINE_SERVER_WS   = "ws://192.168.1.100:8765"
$env:PARALINE_SERVER_REST = "http://192.168.1.100:8056"
$env:CLIENT_API_KEY       = "your-client-api-key"
$env:VIRTUAL_SPEAKER_NAME = "CABLE Output"

# Google Meet Bridge (Chrome extension ↔ Python)
$env:MEET_BRIDGE_PORT     = "9877"
$env:MEET_CHAT_QUEUE_MAX  = "200"
```

### Bước 4: Chạy
```powershell
python -m client.ui.main_app
```

---

## Google Meet Integration Setup (khuyến dùng)

### Bước 1: Cài Chrome Extension
1. Mở Chrome → vào `chrome://extensions`
2. Bật **Developer mode**
3. Chọn **Load unpacked**
4. Trỏ đến thư mục: `paraline-msagent/chrome_extension`

### Bước 2: Kiểm tra kết nối Bridge
1. Chạy `python -m client.ui.main_app`
2. Click icon extension **Paraline Meet Bridge**
3. Nếu thấy **Bridge (Python) = Connected** là OK

### Bước 3: Join cuộc họp
1. Join Google Meet trên Chrome: `meet.google.com/...`
2. Khi vào meeting, extension sẽ tự detect và app sẽ tự start phiên dịch (sau delay ngắn)

---

## Teams Integration Setup (tuỳ chọn)

### Option A: Incoming Webhook (Dễ, Phase 4 early testing)
1. Mở Teams channel muốn nhận bản dịch
2. `...` → `Connectors` → `Incoming Webhook` → Configure
3. Copy URL vào `.env`: `TEAMS_WEBHOOK_URL=https://...`

### Option B: Microsoft Graph API (Production — khuyến dùng)
1. Vào [Azure Active Directory](https://portal.azure.com)
2. `App registrations` → `New registration`
   - Name: `Paraline MSAgent`
   - Account type: Single tenant
3. `API Permissions` → Add:
   - `Chat.ReadWrite` (Application)
   - `ChannelMessage.Send` (Application)
4. `Certificates & secrets` → New client secret
5. Xin IT Admin `Grant admin consent`
6. Điền vào `.env`:
   ```
   TEAMS_TENANT_ID=...
   TEAMS_CLIENT_ID=...
   TEAMS_CLIENT_SECRET=...
   ```

---

## Sử dụng trong cuộc họp

### Google Meet (Chrome)
- Mở Google Meet trên Chrome và đảm bảo extension **Paraline Meet Bridge** đang bật
- App sẽ tự start khi meeting bắt đầu (extension detect)
- Outbound text sẽ được đẩy vào Meet chat tự động

### Dịch slide thủ công
1. Dùng **Snipping Tool** (Win+Shift+S) chụp vùng slide
2. **Ctrl+V** vào Paraline side-panel
3. Ảnh dịch xuất hiện trong ~2-3 giây

---

## Troubleshooting

| Vấn đề | Nguyên nhân | Giải pháp |
|---|---|---|
| Không bắt được audio cuộc họp | VB-Audio/Meet chưa cấu hình đúng | Đảm bảo Meet Speaker = `CABLE Input` và `VIRTUAL_SPEAKER_NAME=CABLE Output` |
| Latency > 2s | Server quá tải / network chậm | Dùng Whisper `medium` thay vì `large-v3` |
| OCR không nhận ký tự Nhật | Font quá nhỏ / ảnh mờ | Chụp ảnh resolution cao hơn |
| Meet không thấy chat lên | Bridge/Extension không chạy | Mở popup extension xem `Connected`; kiểm tra `MEET_BRIDGE_PORT=9877` |
| Teams không nhận message | Graph API token hết hạn | Kiểm tra Azure AD app permissions (nếu dùng Teams) |
| GPU OOM | VRAM không đủ | Đặt `WHISPER_DEVICE=cpu` hoặc dùng model nhỏ hơn |

---

## Architecture Decision Records

### Tại sao dùng Vexa pattern?
Vexa AI là open-source meeting assistant với kiến trúc microservices đã được battle-tested:
- **api-gateway**: WebSocket hub, routes đến các AI services
- **WhisperLive**: Realtime STT với streaming WebSocket
- **transcription-collector**: Thu gom segments, không mất data

Paraline MSAgent giữ nguyên pattern này và thêm:
- **translation-service**: NLLB-200 (JP/EN → VN, hoàn toàn offline)
- **tts-service**: Piper TTS (VN audio, không cần cloud)
- **vision-service**: PaddleOCR + OpenCV (dịch slide)
- **agent-service**: Ollama LLM (tóm tắt cuộc họp)

### Tại sao NLLB thay vì DeepL/Google?
**Bảo mật**: Dữ liệu cuộc họp chiến lược không được rời VMG_STAFF.
NLLB-200 chạy local, chất lượng dịch JP→VN đạt 85%+ BLEU score.

### Tại sao Piper TTS?
Piper là TTS engine nhẹ nhất có chất lượng chấp nhận được cho tiếng Việt,
latency ~200ms trên CPU, không cần GPU.
