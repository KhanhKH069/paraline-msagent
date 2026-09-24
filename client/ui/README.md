# client/ui — UI Layer của Meeting AI Assistant

Đây là tầng giao diện người dùng (GUI) của ứng dụng Meeting AI Assistant, được xây dựng bằng **PyQt6**.

---

## 📁 Cấu trúc thư mục

```
client/ui/
├── main_app.py         # Entry point — khởi động QApplication
├── main_window.py      # Cửa sổ chính, điều phối toàn bộ session
├── config.py           # Cấu hình toàn cục (server URL, API key, CSS)
├── styles.py           # Các hằng số style bổ sung
├── meeting_minutes.py  # Màn hình Biên bản cuộc họp (Meeting Minutes)
└── components/         # Các widget tái sử dụng (xem bên dưới)
```

---

## 🧩 Các Component (components/)

| File | Mô tả |
|---|---|
| `frame_trans.py` | **Frame Dịch thuật** — hiển thị bong bóng văn bản Inbound/Outbound |
| `frame_chat.py` | **Frame Chat** — giao diện trò chuyện với AI |
| `frame_minutes.py` | **Frame Biên bản** — hiển thị Meeting Minutes |
| `splash_screen.py` | **Splash Screen** — màn hình chờ tải ứng dụng |
| `pulse_dot.py` | **Pulse Dot** — chấm xanh nhấp nháy báo hiệu đang thu âm |
| `helpers.py` | Các hàm tiện ích dùng chung cho component |

---

## 🚀 Cách chạy

### Chạy ứng dụng
```bash
python -m client.ui.main_app
```

---

## 🏗️ Kiến trúc

```
main_app.py
    └── main_window.py (MeetingMainWindow)
            ├── FrameTrans       — Dịch thuật Inbound/Outbound
            ├── FrameChat        — Chat AI
            └── FrameMinutes     — Biên bản họp
```

Luồng dữ liệu:
1.  `AudioManager` thu âm từ phần cứng và gọi callback.
2.  `WebSocket Client` gửi chunk âm thanh lên server và nhận kết quả.
3.  `MainWindow` nhận kết quả qua Qt Signal và đẩy vào các Frame tương ứng.

---

## ⚙️ Cấu hình

Các biến môi trường trong file `.env` ảnh hưởng đến UI:

| Biến | Mô tả | Mặc định |
|---|---|---|
| `SERVER_WS` | Địa chỉ WebSocket server | `ws://127.0.0.1:8056` |
| `SERVER_REST` | Địa chỉ REST API server | `http://127.0.0.1:8056` |
| `CLIENT_API_KEY` | API key xác thực | `meeting_client_secret_key_local` |
| `DEBUG_AUDIO` | Lưu file WAV debug vào `debug_audio/` | `0` |
