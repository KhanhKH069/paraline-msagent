# 🟠 Paraline MSAgent

> **Hệ thống Phiên dịch Thời gian thực & Trợ lý AI cho Microsoft Teams**
> Hoạt động 100% offline trên mạng nội bộ VMG_STAFF — không có byte nào rời khỏi hệ thống công ty.

---

## Tổng quan kiến trúc

Paraline MSAgent được xây dựng dựa trên **core pattern của Vexa AI** (api-gateway → WhisperLive → transcription-collector), mở rộng thêm các layer dịch thuật, TTS, Vision và AI Agent.

```
╔══════════════════════════════════════════════════════════════╗
║                    CLIENT GUI APP (Windows)                  ║
║  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   ║
║  │Virtual Spkr │  │  Real Mic    │  │  Screenshot/Paste  │   ║
║  │(Teams Audio)│  │              │  │  (Ctrl+V)          │   ║
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
          ║  💬 JP/EN Text → Microsoft Teams Chat     ║
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
│   ├── teams_integration/        # Microsoft Graph API + Incoming Webhook
│   ├── image_handler/            # Chụp màn hình, paste ảnh, hiển thị kết quả
│   └── ui/                       # PyQt6 Side-panel — dock cạnh Teams
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
| **Outbound** (VN/EN → Teams) | Real Mic → Whisper → NLLB → Teams Chat API | **< 1.0s** |
| **Image** (Slide JP/EN → VN) | Screenshot → PaddleOCR → NLLB → Inpaint → Pillow Render | **< 3.0s** |
| **Agent** (Transcript → Minutes) | Full session text → Ollama Llama 3 → Summary + Action Items | Post-meeting |

## Quick Start

```bash
# 1. Clone & cấu hình
git clone <repo> && cd paraline-msagent
cp .env.example .env
# Sửa VMG_SERVER_IP, TEAMS_* trong .env

# 2. Download AI models
make download-models

# 3. Khởi động server
make all          # = make env + make build + make up

# 4. Kiểm tra health
make health

# 5. Cài Client App trên máy nhân viên
cd client && pip install -r requirements.txt
python -m ui.main_app
```

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
| Teams | Microsoft Graph API / Incoming Webhook |
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
