"""
services/asr-service/core/translator.py

Vietnamese text translation module (VI → EN / JA).
Uses deep_translator (Google Translate, no API key required).

Install:
    pip install deep-translator
"""

from __future__ import annotations

_TRANSLATOR_AVAILABLE = False
_IMPORT_ERROR: str = ""

try:
    from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
    _TRANSLATOR_AVAILABLE = True
except ImportError as e:
    _IMPORT_ERROR = str(e)


def is_available() -> bool:
    """Return True if deep_translator is installed."""
    return _TRANSLATOR_AVAILABLE


def translate(text: str, target_lang: str) -> str:
    """Translate text to the target language using Google Translate.

    Args:
        text:        Vietnamese source text.
        target_lang: BCP-47 language code, e.g. "en" or "ja".

    Returns:
        Translated string, or an error message string if unavailable.
    """
    if not _TRANSLATOR_AVAILABLE:
        return "[deep-translator not installed: pip install deep-translator]"
    if not text or not text.strip():
        return ""
    try:
        translator = GoogleTranslator(source="vi", target=target_lang)
        result = translator.translate(text)
        return result or ""
    except Exception as exc:
        return f"[Translation error ({target_lang}): {exc}]"


def translate_all(text: str) -> dict[str, str]:
    """Translate Vietnamese text to both English and Japanese.

    Args:
        text: Vietnamese source text.

    Returns:
        Dict with keys "en" and "ja".
    """
    return {
        "en": translate(text, "en"),
        "ja": translate(text, "ja"),
    }
