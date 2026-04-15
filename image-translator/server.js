/**
 * server.js — Local dev server
 * Inject API key vào HTML mà không expose trong source code frontend
 * 
 * Chạy: node server.js
 * Hoặc: npm start
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const PORT = process.env.PORT || 3000;
const API_KEY = process.env.GEMINI_API_KEY || '';

if (!API_KEY) {
  console.warn('\n⚠️  Chưa tìm thấy GEMINI_API_KEY trong file .env');
  console.warn('   Tạo file .env và thêm: GEMINI_API_KEY=AIza...\n');
  console.warn('   Lấy API key miễn phí tại: https://aistudio.google.com/apikey\n');
}

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css':  'text/css',
  '.js':   'application/javascript',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.ico':  'image/x-icon',
  '.svg':  'image/svg+xml',
};

const server = http.createServer((req, res) => {
  let filePath = req.url === '/' ? '/index.html' : req.url;
  filePath = path.join(__dirname, filePath);

  const ext = path.extname(filePath);
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      return res.end('Not found');
    }

    // Inject API key vào index.html qua <script> tag
    if (filePath.endsWith('index.html')) {
      let html = data.toString();
      const inject = `<script>window.GEMINI_API_KEY = "${API_KEY}";</script>`;
      html = html.replace('</head>', inject + '\n</head>');
      res.writeHead(200, { 'Content-Type': contentType });
      return res.end(html);
    }

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

server.listen(PORT, () => {
  console.log(`\n✅ Image Translator đang chạy!`);
  console.log(`   Mở trình duyệt: http://localhost:${PORT}\n`);
});
