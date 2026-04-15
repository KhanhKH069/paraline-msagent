// ===== Config =====
// API key được load từ server.js (chạy qua Node) hoặc trực tiếp từ .env khi dùng Vite
// Không bao giờ hardcode API key ở đây!
// API: Google Gemini 2.0 Flash — https://aistudio.google.com/apikey

let imageBase64 = null;
let imageMimeType = null;
let currentTab = 'translation';

// ===== DOM Elements =====
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const uploadSection = document.getElementById('uploadSection');
const resultSection = document.getElementById('resultSection');
const previewImg = document.getElementById('previewImg');
const translateBtn = document.getElementById('translateBtn');
const btnText = document.getElementById('btnText');
const btnIcon = document.getElementById('btnIcon');
const langText = document.getElementById('langText');
const origText = document.getElementById('origText');
const viText = document.getElementById('viText');
const placeholder = document.getElementById('placeholder');
const tabsBar = document.getElementById('tabsBar');
const copyBtn = document.getElementById('copyBtn');
const sourceLang2 = document.getElementById('sourceLang2');

// ===== File Handling =====
fileInput.addEventListener('change', e => {
  if (e.target.files[0]) handleFile(e.target.files[0]);
});

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});

// Paste ảnh từ clipboard (Ctrl+V)
document.addEventListener('paste', e => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      handleFile(item.getAsFile());
      break;
    }
  }
});

function handleFile(file) {
  if (!file.type.startsWith('image/')) {
    alert('Vui lòng chọn file ảnh (JPG, PNG, WEBP, GIF, BMP)');
    return;
  }
  imageMimeType = file.type;
  const reader = new FileReader();
  reader.onload = ev => {
    imageBase64 = ev.target.result.split(',')[1];
    previewImg.src = ev.target.result;
    uploadSection.style.display = 'none';
    resultSection.style.display = 'block';
    // Reset result
    resetResult();
  };
  reader.readAsDataURL(file);
}

document.getElementById('changeImgBtn').addEventListener('click', () => {
  imageBase64 = null; imageMimeType = null;
  fileInput.value = '';
  uploadSection.style.display = 'block';
  resultSection.style.display = 'none';
});

// ===== Translate =====
async function translateImage() {
  if (!imageBase64) return;

  const lang = sourceLang2.value;
  const langHint = lang === 'auto' ? '' : ` Ngôn ngữ nguồn là ${lang}.`;

  setLoading(true);

  const prompt = `Bạn là chuyên gia OCR và dịch thuật chuyên nghiệp.${langHint}

Nhiệm vụ:
1. Trích xuất TOÀN BỘ văn bản trong ảnh, giữ nguyên cấu trúc và xuống dòng.
2. Dịch toàn bộ sang tiếng Việt tự nhiên, trôi chảy, đúng ngữ cảnh.

Trả về JSON hợp lệ (không có markdown, không có backtick, không có text ngoài JSON):
{
  "detected_language": "tên ngôn ngữ phát hiện (ví dụ: Tiếng Nhật, Tiếng Anh)",
  "original_text": "toàn bộ văn bản gốc từ ảnh",
  "vietnamese_translation": "bản dịch tiếng Việt đầy đủ"
}

Nếu ảnh không có văn bản: {"detected_language":"Không có văn bản","original_text":"(ảnh không chứa văn bản)","vietnamese_translation":"(không có gì để dịch)"}`;

  try {
    const apiKey = window.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error('Chưa cấu hình API key. Xem hướng dẫn trong file README.md');
    }

    const GEMINI_MODEL = 'gemini-2.0-flash';
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        contents: [{
          parts: [
            {
              inline_data: {
                mime_type: imageMimeType,
                data: imageBase64
              }
            },
            { text: prompt }
          ]
        }],
        generationConfig: {
          temperature: 0.2,
          maxOutputTokens: 2048,
        }
      })
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      const msg = err?.error?.message || `Lỗi API: ${response.status}`;
      throw new Error(msg);
    }

    const data = await response.json();
    const raw = data?.candidates?.[0]?.content?.parts?.[0]?.text || '';
    const clean = raw.replace(/```json|```/g, '').trim();

    let parsed;
    try { parsed = JSON.parse(clean); }
    catch {
      parsed = {
        detected_language: 'Không xác định',
        original_text: raw,
        vietnamese_translation: '(Lỗi phân tích kết quả từ AI)'
      };
    }

    setResult(parsed);

  } catch (err) {
    setError(err.message);
  }
}

// ===== UI State =====
function resetResult() {
  placeholder.style.display = 'flex';
  viText.style.display = 'none';
  origText.textContent = '';
  tabsBar.style.display = 'none';
  copyBtn.style.display = 'none';
  langText.textContent = 'Chưa dịch';
  document.querySelector('#langDetected .dot').className = 'dot dot-blue';
  translateBtn.disabled = false;
  btnIcon.textContent = '✦';
  btnText.textContent = 'Dịch ngay';
}

function setLoading(active) {
  if (active) {
    translateBtn.disabled = true;
    btnIcon.textContent = '⟳';
    btnText.textContent = 'Đang dịch';
    langText.textContent = 'Đang xử lý...';
    document.querySelector('#langDetected .dot').className = 'dot dot-blue dot-pulse';
    // Show skeleton
    placeholder.style.display = 'none';
    viText.style.display = 'block';
    viText.innerHTML = `<div class="skeleton-lines">
      <div class="skel" style="width:90%"></div>
      <div class="skel" style="width:75%"></div>
      <div class="skel" style="width:85%"></div>
      <div class="skel" style="width:60%"></div>
      <div class="skel" style="width:80%"></div>
    </div>`;
    tabsBar.style.display = 'none';
    copyBtn.style.display = 'none';
  } else {
    translateBtn.disabled = false;
    btnIcon.textContent = '✦';
    btnText.textContent = 'Dịch lại';
  }
}

function setResult(parsed) {
  setLoading(false);
  langText.textContent = parsed.detected_language || 'Không xác định';
  document.querySelector('#langDetected .dot').className = 'dot dot-green';

  origText.textContent = parsed.original_text || '(trống)';
  viText.innerHTML = '';
  viText.textContent = parsed.vietnamese_translation || '(trống)';
  viText.style.display = 'block';
  placeholder.style.display = 'none';
  tabsBar.style.display = 'flex';
  copyBtn.style.display = 'inline-flex';
  switchTab('translation');
}

function setError(msg) {
  setLoading(false);
  viText.innerHTML = `<span style="color:#f87171;">⚠ ${msg}</span>`;
  viText.style.display = 'block';
  placeholder.style.display = 'none';
}

// ===== Tabs =====
function switchTab(tab) {
  currentTab = tab;
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach((t, i) => t.classList.toggle('active', (i === 0 && tab === 'translation') || (i === 1 && tab === 'original')));
  document.getElementById('tabTranslation').style.display = tab === 'translation' ? 'block' : 'none';
  document.getElementById('tabOriginal').style.display = tab === 'original' ? 'block' : 'none';
}

// ===== Copy =====
function copyText() {
  const text = viText.textContent;
  navigator.clipboard.writeText(text).then(() => {
    copyBtn.textContent = '✓ Đã sao chép';
    setTimeout(() => { copyBtn.textContent = '📋 Sao chép'; }, 2000);
  });
}

// ===== Expose globals =====
window.translateImage = translateImage;
window.switchTab = switchTab;
window.copyText = copyText;
