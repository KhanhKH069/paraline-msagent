"""
src/translator/contextual_translator.py

Contextual Chunk Translator:
  1. Nhận câu đầu vào + ngôn ngữ nguồn/đích
  2. Chunk câu thành các đơn vị ngữ nghĩa
  3. Dịch từng chunk với full-sentence context (cross-attention)
  4. Ghép kết quả thành câu hoàn chỉnh
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

from src.chunker import ChunkedSentence, ChunkItem, get_chunker, assign_context_weights


# NLLB-200 Flores language codes
LANG_CODES = {
    "ja": "jpn_Jpan",
    "en": "eng_Latn",
    "vi": "vie_Latn",
}

# Reverse map
CODE_TO_LANG = {v: k for k, v in LANG_CODES.items()}


class ContextualTranslator:
    """
    Dịch câu theo chunk với context awareness.

    Mỗi chunk được dịch bằng NLLB với toàn bộ câu gốc làm context prefix,
    sau đó các chunk dịch được ghép lại và post-processed.
    """

    def __init__(
        self,
        model_path: str = "facebook/nllb-200-distilled-600M",
        device: Optional[str] = None,
        use_chunk_prefix: bool = True,
    ):
        self.model_path = model_path
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.use_chunk_prefix = use_chunk_prefix

        print(f"[ContextualTranslator] Loading model from {model_path}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        self.model = self.model.to(self.device)
        self.model.eval()
        print(f"[ContextualTranslator] Model loaded on {self.device}")

        # Cache chunkers
        self._chunkers: dict = {}

    def _get_chunker(self, lang: str):
        if lang not in self._chunkers:
            self._chunkers[lang] = get_chunker(lang)
        return self._chunkers[lang]

    # ─── Core translate ────────────────────────────────────────────────────

    def translate_sentence(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: int = 256,
        num_beams: int = 4,
    ) -> str:
        """
        Pipeline chính:
          text → chunk → context-aware translate per chunk → assemble
        """
        src_code = LANG_CODES.get(src_lang, src_lang)
        tgt_code = LANG_CODES.get(tgt_lang, tgt_lang)

        # Chunking
        chunker = self._get_chunker(src_lang)
        chunked: ChunkedSentence = chunker.chunk(text)
        chunked = assign_context_weights(chunked)

        if len(chunked.chunks) <= 1 or not self.use_chunk_prefix:
            # Câu ngắn hoặc không chunk được → dịch trực tiếp
            return self._nllb_translate(text, src_code, tgt_code, max_new_tokens, num_beams)

        # Dịch từng chunk với full-sentence context
        translated_chunks: List[str] = []
        for chunk in chunked.chunks:
            translated = self._translate_chunk_with_context(
                chunk=chunk,
                full_sentence=text,
                src_code=src_code,
                tgt_code=tgt_code,
                max_new_tokens=max(32, len(chunk.text.split()) * 4),
                num_beams=num_beams,
            )
            chunk.translated = translated
            translated_chunks.append(translated)

        # Ghép + post-process
        assembled = self._assemble_chunks(translated_chunks, tgt_lang)
        return assembled

    def _translate_chunk_with_context(
        self,
        chunk: ChunkItem,
        full_sentence: str,
        src_code: str,
        tgt_code: str,
        max_new_tokens: int,
        num_beams: int,
    ) -> str:
        """
        Dịch 1 chunk. Input = "[CONTEXT: {full_sentence}] {chunk.text}"
        NLLB encoder sẽ attend đến cả context + chunk.
        """
        # Prepend context để NLLB encoder có full-sentence view
        context_input = f"[CONTEXT: {full_sentence}] {chunk.text}"
        return self._nllb_translate(context_input, src_code, tgt_code, max_new_tokens, num_beams)

    def _nllb_translate(
        self,
        text: str,
        src_lang_code: str,
        tgt_lang_code: str,
        max_new_tokens: int = 256,
        num_beams: int = 4,
    ) -> str:
        """Low-level NLLB translation call."""
        self.tokenizer.src_lang = src_lang_code
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        ).to(self.device)

        forced_bos_token_id = self.tokenizer.lang_code_to_id[tgt_lang_code]

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=max_new_tokens,
                num_beams=num_beams,
                early_stopping=True,
                no_repeat_ngram_size=3,
            )

        result = self.tokenizer.decode(output_ids[0], skip_special_tokens=True)
        return result.strip()

    # ─── Assembler ─────────────────────────────────────────────────────────

    def _assemble_chunks(self, chunks: List[str], tgt_lang: str) -> str:
        """
        Ghép các chunk dịch lại thành câu hoàn chỉnh.
        - Loại bỏ [CONTEXT: ...] prefix nếu có (model đôi khi copy ra)
        - Xử lý punctuation boundary
        - Dedup overlapping translations
        """
        cleaned = []
        for chunk in chunks:
            # Xoá context prefix nếu model vô tình generate ra
            chunk = re.sub(r"\[CONTEXT:.*?\]", "", chunk).strip()
            if chunk:
                cleaned.append(chunk)

        if not cleaned:
            return ""

        # Ghép
        if tgt_lang == "vi":
            joined = " ".join(cleaned)
        elif tgt_lang == "ja":
            # Tiếng Nhật không có spaces giữa morpheme
            joined = "".join(cleaned)
        else:
            joined = " ".join(cleaned)

        # Post-process: chuẩn hoá spaces + capitalize đầu câu
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            joined = joined[0].upper() + joined[1:]

        return joined

    # ─── Batch translate ───────────────────────────────────────────────────

    def translate_batch(
        self,
        sentences: List[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs,
    ) -> List[str]:
        """Dịch nhiều câu (sequential, không pad batch vì context approach)."""
        return [
            self.translate_sentence(s, src_lang, tgt_lang, **kwargs)
            for s in sentences
        ]

    def translate_with_details(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
    ) -> dict:
        """
        Trả về dict đầy đủ: chunk breakdown + translation per chunk.
        Hữu ích cho debug và notebook visualization.
        """
        src_code = LANG_CODES.get(src_lang, src_lang)
        tgt_code = LANG_CODES.get(tgt_lang, tgt_lang)

        chunker = self._get_chunker(src_lang)
        chunked: ChunkedSentence = chunker.chunk(text)
        chunked = assign_context_weights(chunked)

        chunk_details = []
        translated_parts = []
        for chunk in chunked.chunks:
            t = self._translate_chunk_with_context(
                chunk=chunk,
                full_sentence=text,
                src_code=src_code,
                tgt_code=tgt_code,
                max_new_tokens=64,
                num_beams=2,
            )
            chunk.translated = t
            translated_parts.append(t)
            chunk_details.append({
                "chunk": chunk.text,
                "type": chunk.chunk_type.value,
                "dep_role": chunk.dep_role,
                "position_ratio": chunk.position_ratio,
                "context_weight": chunk.context_weight,
                "translated": t,
            })

        final = self._assemble_chunks(translated_parts, tgt_lang)
        return {
            "original": text,
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "chunks": chunk_details,
            "final_translation": final,
        }
