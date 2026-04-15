# 🖼️ Image Translator — Dịch thuật hình ảnh bằng Gemini AI

Ứng dụng dịch văn bản từ hình ảnh sang **tiếng Việt**, sử dụng Google **Gemini 2.0 Flash**.  
Hỗ trợ: Tiếng Anh, Nhật, Hàn, Trung, Pháp, Đức, Thái và nhiều ngôn ngữ khác.

---

## 🚀 Cài đặt & Chạy (3 bước)

### Bước 1: Cài Node.js
Tải về tại https://nodejs.org — chọn bản **LTS** (v18 trở lên)

### Bước 2: Tạo file `.env` và điền API key
```bash
# Copy file mẫu
cp .env.example .env
```
Mở file `.env` bằng Notepad / VS Code, thay thế `AIzaSy...` bằng API key thật của bạn.

> **Lấy API key ở đâu?**  
> Truy cập https://aistudio.google.com/apikey → Create API Key  
> API key có dạng: `AIzaSyXXXXXXXXXXXXXXXXXXX`  
> ✅ **Hoàn toàn miễn phí** — 1,500 request/ngày free tier

### Bước 3: Cài dependencies và chạy
```bash
# Cài thư viện (chỉ cần làm 1 lần)
npm install

# Chạy server
npm start
```

Mở trình duyệt và vào: **http://localhost:3000**

---

## 🎯 Tính năng

- **Upload ảnh** bằng kéo thả, click chọn file, hoặc dán từ clipboard (Ctrl+V)
- **Nhận diện ngôn ngữ tự động** — hoặc chọn thủ công
- **Xem song song**: Văn bản gốc & Bản dịch tiếng Việt
- **Sao chép** bản dịch 1 click
- Hỗ trợ: JPG, PNG, WEBP, GIF, BMP

---

## 💡 Tại sao dùng Gemini 2.0 Flash?

| | Gemini 2.0 Flash | Claude Haiku | OpenAI GPT-4o-mini |
|---|---|---|---|
| Độ chính xác dịch thuật | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Đọc chữ Nhật/Hàn/Trung | ✅ Xuất sắc | ✅ Tốt | ✅ Tốt |
| Dịch tự nhiên sang Việt | ✅ Xuất sắc | ✅ Tốt | ✅ Tốt |
| Giá (input 1M token) | **$0.10** | $0.80 | $0.15 |
| Free tier | **1,500 req/ngày** | ❌ | ❌ |
| Setup đơn giản | ✅ 1 API key | ✅ 1 API key | ✅ 1 API key |

→ **Gemini 2.0 Flash** là lựa chọn tốt nhất: **rẻ hơn 8x** so với Claude Haiku, có free tier hào phóng, OCR tiếng Á rất mạnh.

---

## 📁 Cấu trúc project

```
image-translator/
├── index.html          # Giao diện chính
├── server.js           # Local server (inject API key an toàn)
├── package.json        # Config Node.js
├── .env.example        # Mẫu file cấu hình
├── .env                # ← Bạn tự tạo, chứa API key (không commit git!)
├── .gitignore
└── src/
    ├── style.css       # Giao diện
    └── app.js          # Logic dịch thuật
```

---

## ⚠️ Bảo mật API Key

- **KHÔNG** commit file `.env` lên GitHub
- **KHÔNG** hardcode API key trong code
- File `.gitignore` đã bảo vệ file `.env` rồi
- API key chỉ được inject server-side qua `server.js`

---

## 🔧 Tuỳ chỉnh model

Muốn đổi model AI, mở `src/app.js` tìm dòng:
```js
const GEMINI_MODEL = 'gemini-2.0-flash';
```
Các model có thể dùng:
- `gemini-2.0-flash` — Nhanh, rẻ nhất, khuyến nghị ✅
- `gemini-2.0-flash-thinking-exp` — Suy luận sâu hơn
- `gemini-1.5-pro` — Mạnh hơn, phù hợp ảnh phức tạp

---

## ❓ Gặp lỗi?

**"Chưa cấu hình API key"** → Kiểm tra file `.env` đã có `GEMINI_API_KEY=AIzaSy...` chưa

**"Lỗi API: 400"** → API key sai định dạng, kiểm tra lại tại aistudio.google.com

**"Lỗi API: 403"** → API key chưa được kích hoạt hoặc không có quyền, tạo key mới

**"Lỗi API: 429"** → Đã vượt 1,500 req/ngày (free tier), chờ hôm sau hoặc upgrade

**Port 3000 bị dùng** → Thêm `PORT=3001` vào file `.env`
