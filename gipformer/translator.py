#!/usr/bin/env python3
"""
Gipformer Translator Module
Dịch văn bản tiếng Việt sang tiếng Anh và tiếng Nhật.
Sử dụng deep_translator (Google Translate, không cần API key).

Cài đặt:
    pip install deep-translator
"""

from __future__ import annotations

_TRANSLATOR_AVAILABLE = False
_IMPORT_ERROR: str = ""

try:
    from deep_translator import GoogleTranslator
    _TRANSLATOR_AVAILABLE = True
except ImportError as e:
    _IMPORT_ERROR = str(e)


def is_available() -> bool:
    """Kiểm tra xem deep_translator đã được cài chưa."""
    return _TRANSLATOR_AVAILABLE


def translate(text: str, target_lang: str) -> str:
    """
    Dịch văn bản sang ngôn ngữ đích.

    Args:
        text       : Văn bản cần dịch (tiếng Việt).
        target_lang: Mã ngôn ngữ đích, ví dụ 'en' hoặc 'ja'.

    Returns:
        Văn bản đã dịch, hoặc chuỗi rỗng nếu lỗi.
    """
    if not _TRANSLATOR_AVAILABLE:
        return "[deep-translator chưa cài: pip install deep-translator]"
    if not text or not text.strip():
        return ""
    try:
        translator = GoogleTranslator(source="vi", target=target_lang)
        result = translator.translate(text)
        return result or ""
    except Exception as exc:
        return f"[Lỗi dịch ({target_lang}): {exc}]"


def translate_all(text: str) -> dict[str, str]:
    """
    Dịch văn bản sang cả tiếng Anh lẫn tiếng Nhật.

    Args:
        text: Văn bản gốc tiếng Việt.

    Returns:
        dict với keys 'en' và 'ja'.
    """
    return {
        "en": translate(text, "en"),
        "ja": translate(text, "ja"),
    }


def print_translations(vi_text: str, indent: str = "   ") -> None:
    """
    In kết quả dịch ra console theo định dạng đẹp.

    Args:
        vi_text: Văn bản gốc tiếng Việt.
        indent : Chuỗi thụt lề cho mỗi dòng.
    """
    if not vi_text or not vi_text.strip():
        return

    if not _TRANSLATOR_AVAILABLE:
        print(f"{indent}⚠️  deep-translator chưa cài. Chạy: pip install deep-translator")
        return

    print(f"{indent}🌐 Đang dịch...")
    translations = translate_all(vi_text)

    en = translations["en"]
    ja = translations["ja"]

    print(f"{indent}🇬🇧 EN: {en}")
    print(f"{indent}🇯🇵 JA: {ja}")
