#!/usr/bin/env python3
"""
scripts/test_pipeline.py
Kiểm tra end-to-end pipeline bằng test audio/image.
python scripts/test_pipeline.py [--server 192.168.1.100]

Tests:
  1. Translation:  "こんにちは" → "Xin chào"
  2. TTS:          "Xin chào" → WAV audio (check non-empty)
  3. Image:        Test PNG với chữ EN → translated image
"""
import argparse
import base64
import sys
import time

import requests

def test_translation(base: str):
    print("\n[1] Translation (JP→VN):")
    r = requests.post(f"{base}:8002/translate", json={
        "text": "こんにちは、今日の会議を始めましょう。",
        "src_lang": "jpn_Jpan",
        "tgt_lang": "vie_Latn",
    }, timeout=30)
    assert r.ok, f"HTTP {r.status_code}"
    d = r.json()
    print(f"   Input:  こんにちは、今日の会議を始めましょう。")
    print(f"   Output: {d['translated_text']}")
    print(f"   Latency: {d['latency_ms']:.0f}ms")
    assert d["translated_text"], "Empty translation"
    print("   ✅ PASS")


def test_tts(base: str):
    print("\n[2] TTS (VN text → audio):")
    r = requests.post(f"{base}:8003/synthesize", json={
        "text": "Xin chào, cuộc họp bắt đầu.",
    }, timeout=15)
    assert r.ok, f"HTTP {r.status_code}"
    d = r.json()
    audio_bytes = base64.b64decode(d["audio_b64"])
    print(f"   Audio size: {len(audio_bytes):,} bytes | SR={d['sample_rate']}")
    assert len(audio_bytes) > 1000, "Audio too short"
    print(f"   Latency: {d['latency_ms']:.0f}ms")
    print("   ✅ PASS")


def test_image_translate(base: str):
    print("\n[3] Image Translation (EN slide → VN):")
    # Create a tiny test PNG with PIL
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        img = Image.new("RGB", (400, 100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 35), "System Architecture Overview", fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        print("   ⚠️  PIL not installed, skipping image test")
        return

    r = requests.post(f"{base}:8004/translate/image", json={
        "session_id": "test-session",
        "image_b64":  img_b64,
        "src_lang":   "eng_Latn",
        "tgt_lang":   "vie_Latn",
    }, timeout=15)
    assert r.ok, f"HTTP {r.status_code}"
    d = r.json()
    print(f"   OCR blocks found: {len(d['ocr_blocks'])}")
    for b in d["ocr_blocks"]:
        print(f"   '{b['original_text']}' → '{b['translated_text']}'")
    print(f"   Latency: {d['total_latency_ms']:.0f}ms")
    print("   ✅ PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="localhost")
    args = parser.parse_args()
    base = f"http://{args.server}"

    print(f"🟠 Paraline MSAgent — Pipeline Test ({args.server})")
    print("=" * 50)

    failures = []
    for test_fn in [test_translation, test_tts, test_image_translate]:
        try:
            test_fn(base)
        except Exception as e:
            print(f"   ❌ FAIL: {e}")
            failures.append(test_fn.__name__)

    print("\n" + "=" * 50)
    if not failures:
        print("✅ All pipeline tests passed!")
    else:
        print(f"❌ Failed: {', '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
