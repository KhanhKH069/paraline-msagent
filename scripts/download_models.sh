#!/usr/bin/env bash
# scripts/download_models.sh
# Download tất cả AI models trước khi chạy `make up`
# Chạy một lần trên VMG AI Server.

set -e
MODELS_DIR="${MODELS_DIR:-./models-cache}"
mkdir -p "$MODELS_DIR/whisper" "$MODELS_DIR/nllb" "$MODELS_DIR/piper" "$MODELS_DIR/fonts"

echo "📦 Paraline MSAgent — Model Downloader"
echo "  Models dir: $MODELS_DIR"
echo ""

# ─────────────────────────────────────────────
# 1. Faster-Whisper (large-v3)
# ─────────────────────────────────────────────
echo "⏳ [1/4] Downloading Faster-Whisper large-v3..."
python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('large-v3', device='cpu', compute_type='int8', download_root='$MODELS_DIR/whisper')
print('✅ Whisper large-v3 downloaded')
"

# ─────────────────────────────────────────────
# 2. NLLB-200 Translation
# ─────────────────────────────────────────────
echo "⏳ [2/4] Downloading NLLB-200-distilled-600M..."
python3 -c "
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
model_name = 'facebook/nllb-200-distilled-600M'
AutoTokenizer.from_pretrained(model_name, cache_dir='$MODELS_DIR/nllb')
AutoModelForSeq2SeqLM.from_pretrained(model_name, cache_dir='$MODELS_DIR/nllb')
print('✅ NLLB-200 downloaded')
"

# ─────────────────────────────────────────────
# 3. Piper TTS — Vietnamese voice
# ─────────────────────────────────────────────
echo "⏳ [3/4] Downloading Piper TTS vi_VN-vivos-medium..."
PIPER_RELEASE="https://github.com/rhasspy/piper/releases/download/2023.11.14-2"
VOICE="vi_VN-vivos-medium"
wget -q --show-progress -P "$MODELS_DIR/piper/" \
  "$PIPER_RELEASE/$VOICE.onnx" \
  "$PIPER_RELEASE/$VOICE.onnx.json"
echo "✅ Piper $VOICE downloaded"

# ─────────────────────────────────────────────
# 4. Font for image rendering
# ─────────────────────────────────────────────
echo "⏳ [4/4] Downloading NotoSansCJK font..."
wget -q --show-progress -P "$MODELS_DIR/fonts/" \
  "https://github.com/googlefonts/noto-cjk/raw/main/Sans/Variable/OTC/NotoSansCJK-VF.otf.ttc"
# Rename for consistency
mv "$MODELS_DIR/fonts/NotoSansCJK-VF.otf.ttc" "$MODELS_DIR/fonts/NotoSansCJK-Regular.ttc" 2>/dev/null || true
echo "✅ Font downloaded"

echo ""
echo "🎉 All models downloaded to $MODELS_DIR"
echo "   You can now run: make up"
