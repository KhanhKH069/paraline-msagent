# 🟠 Paraline MSAgent

> **Hệ thống Phiên dịch Thời gian thực & Trợ lý AI cho Google Meet (Chrome Extension)**
> Hoạt động 100% offline trên mạng nội bộ VMG_STAFF — không có byte nào rời khỏi hệ thống công ty.

---

## Tổng quan kiến trúc

Paraline MSAgent được xây dựng dựa trên **core pattern của Vexa AI** (api-gateway → WhisperLive → transcription-collector), mở rộng thêm các layer dịch thuật, TTS, Vision và AI Agent.

```
╔══════════════════════════════════════════════════════════════╗
║                    CLIENT GUI APP (Windows)                  ║
║  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   ║
║  │Virtual Spkr │  │  Real Mic    │  │  Screenshot/Paste  │   ║
║  │(Meet Audio) │  │              │  │  (Ctrl+V)          │   ║
║  └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘   ║
║         │ JP/EN Raw      │ VN/EN Raw          │ Image B64    ║
║         ▼                ▼                    ▼              ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │           WebSocket Stream Controller                 │    ║
║  │  Audio Router + Mixer + Volume Control               │    ║
║  └───────────────────────┬──────────────────────────────┘    ║
║                          │ WebSocket (LAN)                   ║
╚══════════════════════════╪══════════════════════════════════╝
                           │
          ╔════════════════╪═════════════════════════╗
          ║      VMG AI SERVER (VMG_STAFF LAN)        ║
          ║                ▼                          ║
          ║  ┌─────────────────────────────────┐      ║
          ║  │     api-gateway :8056/:8765      │      ║
          ║  │  (Vexa pattern: routes + WS)    │      ║
          ║  └───┬──────┬──────┬──────┬────────┘      ║
          ║      │      │      │      │               ║
          ║      ▼      ▼      ▼      ▼               ║
          ║  [Whisper][NLLB][Piper][PaddleOCR]        ║
          ║  [  ASR  ][Trans][TTS ][+OpenCV  ]        ║
          ║                                            ║
          ║  ┌──────────────────────────────────┐     ║
          ║  │  transcription-collector :8006   │     ║
          ║  │  (Vexa pattern: stores segments) │     ║
          ║  └──────────────────────────────────┘     ║
          ║                                            ║
          ║  ┌──────────────────────────────────┐     ║
          ║  │  agent-service (Ollama LLM)       │     ║
          ║  │  Meeting Minutes + Action Items   │     ║
          ║  └──────────────────────────────────┘     ║
          ╚════════════════════════════════════════════╝
                           │
          ╔════════════════╪═════════════════════════╗
          ║        OUTPUTS                            ║
          ║  🎧 VN Audio → Real Headphone             ║
          ║  📝 Subtitle → Side-panel overlay         ║
          ║  💬 Text → Google Meet Chat (Extension)   ║
          ║  🖼️  Translated Slide Image → Side-panel   ║
          ╚════════════════════════════════════════════╝
```

## Cấu trúc dự án

```
paraline-msagent/
├── services/                     # VMG AI Server — Docker microservices
│   ├── api-gateway/              # FastAPI gateway + WebSocket hub (Vexa: api-gateway)
│   ├── admin-api/                # Quản trị server (Vexa: admin-api)
│   ├── whisperlive-wrapper/      # Faster-Whisper realtime STT (Vexa: WhisperLive)
│   ├── transcription-collector/  # Thu gom & lưu transcript (Vexa: transcription-collector)
│   ├── translation-service/      # NLLB-200 machine translation
│   ├── tts-service/              # Piper TTS → Vietnamese audio
│   ├── vision-service/           # PaddleOCR + OpenCV inpainting + Pillow render
│   ├── agent-service/            # Ollama LLM → Meeting Minutes + Action Items
│   ├── session-manager/          # Quản lý phiên họp Teams
│   └── database/                 # PostgreSQL models + migrations (Vexa pattern)
├── client/                       # Windows GUI App — nhẹ, cài trên máy nhân viên
│   ├── audio_router/             # VB-Audio Virtual Cable routing
│   ├── websocket_client/         # WebSocket stream controller (inbound + outbound)
│   ├── meet_integration/         # Google Meet bridge server + client
│   ├── teams_integration/        # (tuỳ chọn) Microsoft Graph API + Incoming Webhook
│   ├── image_handler/            # Chụp màn hình, paste ảnh, hiển thị kết quả
│   └── ui/                       # PyQt6 Side-panel — dock cạnh cửa sổ họp
├── chrome_extension/             # Google Meet extension (detect meeting + inject chat)
├── shared/                       # Schemas, utils dùng chung client ↔ server
├── scripts/                      # Download models, setup, health check
├── docs/                         # Tài liệu kỹ thuật chi tiết
├── docker-compose.yml            # Khởi động toàn bộ server stack
├── Makefile                      # make all / make up / make logs ...
└── .env.example                  # Template cấu hình
```

## Pipelines xử lý

| Pipeline | Flow | Target Latency |
|---|---|---|
| **Inbound** (JP/EN → VN) | Virtual Speaker → Whisper → NLLB → Piper → Headphone + Subtitle | **< 1.0s** |
| **Outbound** (VN/EN → Meet) | Real Mic → Whisper → NLLB → Meet Chat (Extension) | **< 1.0s** |
| **Image** (Slide JP/EN → VN) | Screenshot → PaddleOCR → NLLB → Inpaint → Pillow Render | **< 3.0s** |
| **Agent** (Transcript → Minutes) | Full session text → Ollama Llama 3 → Summary + Action Items | Post-meeting |

## Quick Start

```bash
# 1. Clone & cấu hình
git clone <repo> && cd paraline-msagent
cp .env.example .env
# Sửa VMG_SERVER_IP, CLIENT_API_KEY, MEET_* trong .env

# 2. Download AI models
make download-models

# 3. Khởi động server
make all          # = make env + make build + make up

# 4. Kiểm tra health
make health

# 5. Cài Client App trên máy nhân viên
cd client && pip install -r requirements.txt
python -m client.ui.main_app
```

## Quick Start (Google Meet)

### 1) Cài Chrome Extension
1. Mở Chrome → `chrome://extensions`
2. Bật **Developer mode**
3. **Load unpacked** → chọn thư mục `chrome_extension/`

### 2) Chạy app client
Trên Windows (máy đang join Meet):

```powershell
cd paraline-msagent\client
pip install -r requirements.txt
python -m client.ui.main_app
```

### 3) Join Google Meet
- Join meeting trên Chrome: `meet.google.com/...`
- Click icon **Paraline Meet Bridge**:
  - **Bridge (Python)**: `Connected`
  - **Cuộc họp**: `Active`
- Khi outbound có text, extension sẽ tự **inject** vào Meet chat.

> Chi tiết hơn xem `docs/SETUP.md` (mục “Google Meet Integration Setup”).

## Tech Stack

| Layer | Technology |
|---|---|
| STT | faster-whisper (large-v3) — Vexa WhisperLive pattern |
| Translation | NLLB-200-distilled-600M (facebook) |
| TTS | Piper TTS (vi_VN-vivos-medium) |
| OCR | PaddleOCR (jp + en) |
| Image Processing | OpenCV TELEA inpaint + Pillow render |
| LLM | Ollama — Llama 3 8B / Gemma 3 9B |
| Audio Routing | VB-Audio Virtual Cable (Windows) |
| Transport | WebSocket over LAN (< 1ms latency) |
| Meet | Chrome Extension + local bridge (HTTP) |
| Teams | (tuỳ chọn) Microsoft Graph API / Incoming Webhook |
| GUI | PyQt6 (frameless side-panel) |
| Server | FastAPI + uvicorn |
| Orchestration | Docker Compose (Vexa pattern) |
| DB | PostgreSQL 15 + Redis 7 |

## Bảo mật

- ✅ **100% offline** — zero external API calls
- ✅ Tất cả AI models chạy local trên VMG_STAFF
- ✅ WebSocket chỉ bind trên LAN interface
- ✅ Không log raw audio — chỉ log transcript đã xử lý
- ✅ API key authentication giữa client ↔ server

## Roadmap (5 Phases)

- [ ] **Phase 1** — AI Server Core: Whisper + NLLB + Piper APIs
- [ ] **Phase 2** — Audio Client App + Virtual Audio Cable routing
- [ ] **Phase 3** — Image Translation Pipeline (OCR + Inpaint)
- [ ] **Phase 4** — Teams Chat Integration (Graph API)
- [ ] **Phase 5** — AI Meeting Agent (Meeting Minutes + Action Items)
