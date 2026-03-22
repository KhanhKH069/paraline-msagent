"""
src/chunker/sentence_chunker.py

Phân đoạn câu thành các chunk có ngữ nghĩa theo ngữ pháp.
Hỗ trợ: Tiếng Nhật (ja), Tiếng Anh (en), Tiếng Việt (vi)

Ý tưởng:
  1. Parse cú pháp câu bằng spaCy
  2. Trích xuất chunks (NP, VP, PP, SubClause, v.v.)
  3. Gắn nhãn context vector cho từng chunk (vị trí + vai trò)
  4. Trả về list[ChunkItem] sẵn sàng cho translation pipeline
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import spacy
from spacy.tokens import Doc, Span


# ─── Data models ────────────────────────────────────────────────────────────

class ChunkType(str, Enum):
    NP   = "NP"     # Noun Phrase       — "the red car"
    VP   = "VP"     # Verb Phrase       — "is running fast"
    PP   = "PP"     # Prepositional Ph. — "on the table"
    ADJP = "ADJP"   # Adjective Phrase  — "very happy"
    ADVP = "ADVP"   # Adverb Phrase     — "quite slowly"
    SBAR = "SBAR"   # Sub-clause        — "because it rained"
    ROOT = "ROOT"   # Full sentence fallback
    MISC = "MISC"   # Miscellaneous


@dataclass
class ChunkItem:
    text: str
    chunk_type: ChunkType
    start_token: int        # index trong câu gốc
    end_token: int
    position_ratio: float   # 0.0 (đầu câu) → 1.0 (cuối câu)
    dep_role: str           # grammatical role: subj, obj, mod, ...
    head_text: str          # head token của chunk
    lang: str               # "ja" | "en" | "vi"

    # Filled sau context embedding step
    context_weight: float = 1.0   # quan trọng = 1.0, bổ trợ < 1.0
    translated: Optional[str] = None


@dataclass
class ChunkedSentence:
    original: str
    lang: str
    tokens: List[str]
    chunks: List[ChunkItem] = field(default_factory=list)

    @property
    def chunk_texts(self) -> List[str]:
        return [c.text for c in self.chunks]

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "lang": self.lang,
            "tokens": self.tokens,
            "chunks": [
                {
                    "text": c.text,
                    "type": c.chunk_type.value,
                    "start": c.start_token,
                    "end": c.end_token,
                    "position_ratio": round(c.position_ratio, 3),
                    "dep_role": c.dep_role,
                    "head": c.head_text,
                    "context_weight": c.context_weight,
                }
                for c in self.chunks
            ],
        }


# ─── Language-specific chunkers ─────────────────────────────────────────────

class BaseChunker:
    """Abstract chunker — mỗi ngôn ngữ subclass lại."""

    def __init__(self, spacy_model: str):
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            raise OSError(
                f"spaCy model '{spacy_model}' chưa được cài.\n"
                f"Chạy: python -m spacy download {spacy_model}"
            )

    def chunk(self, text: str) -> ChunkedSentence:
        raise NotImplementedError

    def _position_ratio(self, token_idx: int, total: int) -> float:
        return token_idx / max(total - 1, 1)

    def _dep_role(self, span: Span) -> str:
        """Lấy vai trò cú pháp của span qua root token."""
        root = span.root
        dep = root.dep_.lower()
        if dep in {"nsubj", "nsubjpass"}:
            return "subj"
        if dep in {"dobj", "obj", "pobj"}:
            return "obj"
        if dep in {"amod", "advmod", "npadvmod"}:
            return "mod"
        if dep in {"prep", "agent"}:
            return "prep"
        if dep in {"relcl", "advcl", "ccomp", "xcomp"}:
            return "clause"
        return dep or "misc"

    def _build_chunk_item(
        self,
        span: Span,
        chunk_type: ChunkType,
        total_tokens: int,
        lang: str,
    ) -> ChunkItem:
        text = span.text.strip()
        start = span.start
        end = span.end
        return ChunkItem(
            text=text,
            chunk_type=chunk_type,
            start_token=start,
            end_token=end,
            position_ratio=self._position_ratio(start, total_tokens),
            dep_role=self._dep_role(span),
            head_text=span.root.text,
            lang=lang,
        )


class EnglishChunker(BaseChunker):
    """Chunker cho tiếng Anh — dùng spaCy noun chunks + custom VP/PP."""

    def __init__(self):
        super().__init__("en_core_web_sm")

    def chunk(self, text: str) -> ChunkedSentence:
        doc: Doc = self.nlp(text)
        tokens = [t.text for t in doc]
        chunks: List[ChunkItem] = []

        covered = set()  # token indices đã được gắn vào chunk

        # 1) Noun Phrases — spaCy có sẵn noun_chunks
        for nc in doc.noun_chunks:
            chunks.append(
                self._build_chunk_item(nc, ChunkType.NP, len(tokens), "en")
            )
            covered.update(range(nc.start, nc.end))

        # 2) Verb + object compound (VP-style) — root verb + children
        for token in doc:
            if token.pos_ == "VERB" and token.dep_ in {"ROOT", "relcl", "advcl", "ccomp"}:
                verb_span_indices = [token.i] + [
                    c.i for c in token.children
                    if c.dep_ in {"aux", "auxpass", "advmod", "neg", "prt"}
                ]
                verb_span_indices = sorted(set(verb_span_indices))
                if len(verb_span_indices) >= 1:
                    start = verb_span_indices[0]
                    end = verb_span_indices[-1] + 1
                    span = doc[start:end]
                    item = self._build_chunk_item(span, ChunkType.VP, len(tokens), "en")
                    chunks.append(item)

        # 3) Prepositional Phrases
        for token in doc:
            if token.dep_ == "prep":
                pp_end = token.i + 1
                for child in token.subtree:
                    pp_end = max(pp_end, child.i + 1)
                span = doc[token.i:pp_end]
                if len(span) > 1:
                    item = self._build_chunk_item(span, ChunkType.PP, len(tokens), "en")
                    chunks.append(item)

        # 4) Fallback nếu không có chunk nào
        if not chunks:
            full_span = doc[0:len(doc)]
            chunks.append(
                self._build_chunk_item(full_span, ChunkType.ROOT, len(tokens), "en")
            )

        # Sắp xếp theo vị trí xuất hiện
        chunks.sort(key=lambda c: c.start_token)
        return ChunkedSentence(original=text, lang="en", tokens=tokens, chunks=chunks)


class JapaneseChunker(BaseChunker):
    """
    Chunker cho tiếng Nhật.
    Nhật không có spaces → spaCy ja_core_news_sm xử lý morpheme.
    Ta group theo bunsetsu-style: dependency arcs.
    """

    def __init__(self):
        super().__init__("ja_core_news_sm")

    def chunk(self, text: str) -> ChunkedSentence:
        doc: Doc = self.nlp(text)
        tokens = [t.text for t in doc]
        chunks: List[ChunkItem] = []

        # Nhóm tokens theo head (bunsetsu approximation)
        bunsetsu_groups: dict[int, list] = {}
        for token in doc:
            head_idx = token.head.i
            bunsetsu_groups.setdefault(head_idx, []).append(token.i)

        for head_idx, member_indices in sorted(bunsetsu_groups.items()):
            all_indices = sorted(set(member_indices + [head_idx]))
            start = all_indices[0]
            end = all_indices[-1] + 1
            span = doc[start:end]
            head_token = doc[head_idx]

            # Phân loại chunk_type theo POS của head
            pos = head_token.pos_
            if pos in {"NOUN", "PROPN", "NUM", "PRON"}:
                ctype = ChunkType.NP
            elif pos in {"VERB", "AUX"}:
                ctype = ChunkType.VP
            elif pos in {"ADJ"}:
                ctype = ChunkType.ADJP
            elif pos in {"ADV"}:
                ctype = ChunkType.ADVP
            elif pos in {"ADP"}:
                ctype = ChunkType.PP
            else:
                ctype = ChunkType.MISC

            item = self._build_chunk_item(span, ctype, len(tokens), "ja")
            chunks.append(item)

        if not chunks:
            span = doc[0:len(doc)]
            chunks.append(
                self._build_chunk_item(span, ChunkType.ROOT, len(tokens), "ja")
            )

        chunks.sort(key=lambda c: c.start_token)
        return ChunkedSentence(original=text, lang="ja", tokens=tokens, chunks=chunks)


class VietnameseChunker(BaseChunker):
    """
    Chunker cho tiếng Việt.
    Dùng vi_core_news_lg (cần cài thêm).
    Fallback: regex-based chunker nếu model chưa có.
    """

    def __init__(self):
        try:
            super().__init__("vi_core_news_lg")
            self._use_regex = False
        except OSError:
            print("[VietnameseChunker] Falling back to regex chunker.")
            self.nlp = None
            self._use_regex = True

    def chunk(self, text: str) -> ChunkedSentence:
        if self._use_regex:
            return self._regex_chunk(text)
        return self._spacy_chunk(text)

    def _spacy_chunk(self, text: str) -> ChunkedSentence:
        doc: Doc = self.nlp(text)
        tokens = [t.text for t in doc]
        chunks: List[ChunkItem] = []

        for nc in doc.noun_chunks:
            chunks.append(
                self._build_chunk_item(nc, ChunkType.NP, len(tokens), "vi")
            )

        for token in doc:
            if token.pos_ == "VERB" and token.dep_ == "ROOT":
                children_idx = [
                    c.i for c in token.children
                    if c.dep_ in {"aux", "advmod", "neg"}
                ]
                span_indices = sorted([token.i] + children_idx)
                if span_indices:
                    span = doc[span_indices[0]:span_indices[-1] + 1]
                    item = self._build_chunk_item(span, ChunkType.VP, len(tokens), "vi")
                    chunks.append(item)

        if not chunks:
            full = doc[0:len(doc)]
            chunks.append(
                self._build_chunk_item(full, ChunkType.ROOT, len(tokens), "vi")
            )

        chunks.sort(key=lambda c: c.start_token)
        return ChunkedSentence(original=text, lang="vi", tokens=tokens, chunks=chunks)

    def _regex_chunk(self, text: str) -> ChunkedSentence:
        """Regex fallback: tách theo dấu câu + từ nối thông dụng."""
        # Tiếng Việt: tách theo từ nối phổ biến
        SPLIT_WORDS = r"\b(và|nhưng|hoặc|vì|nên|do|mà|khi|nếu|tuy|dù|để|rằng|rằng là)\b"
        tokens = text.split()
        parts = re.split(SPLIT_WORDS, text, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()]

        chunks = []
        cursor = 0
        for i, part in enumerate(parts):
            part_tokens = part.split()
            n = len(part_tokens)
            ctype = ChunkType.NP if i % 2 == 0 else ChunkType.SBAR
            chunks.append(
                ChunkItem(
                    text=part,
                    chunk_type=ctype,
                    start_token=cursor,
                    end_token=cursor + n,
                    position_ratio=self._position_ratio(cursor, len(tokens)),
                    dep_role="misc",
                    head_text=part_tokens[0] if part_tokens else "",
                    lang="vi",
                )
            )
            cursor += n

        return ChunkedSentence(original=text, lang="vi", tokens=tokens, chunks=chunks)


# ─── Factory ─────────────────────────────────────────────────────────────────

_CHUNKER_MAP: dict[str, type] = {
    "en": EnglishChunker,
    "ja": JapaneseChunker,
    "vi": VietnameseChunker,
}


def get_chunker(lang: str) -> BaseChunker:
    """Factory: trả về chunker tương ứng với ngôn ngữ."""
    lang = lang.lower().split("_")[0]  # "ja_core" → "ja"
    if lang not in _CHUNKER_MAP:
        raise ValueError(f"Unsupported language: {lang}. Supported: {list(_CHUNKER_MAP.keys())}")
    return _CHUNKER_MAP[lang]()


# ─── Context weight assignment ────────────────────────────────────────────────

def assign_context_weights(chunked: ChunkedSentence) -> ChunkedSentence:
    """
    Gán context_weight cho từng chunk:
    - Subject / Main verb → weight cao (1.0)
    - Object → 0.9
    - PP / Modifier → 0.7
    - MISC → 0.5
    Dùng để weight loss trong contextual training.
    """
    ROLE_WEIGHTS = {
        "subj": 1.0,
        "obj": 0.9,
        "clause": 0.85,
        "prep": 0.7,
        "mod": 0.65,
        "misc": 0.5,
    }
    TYPE_WEIGHTS = {
        ChunkType.ROOT: 1.0,
        ChunkType.VP: 1.0,
        ChunkType.NP: 0.9,
        ChunkType.SBAR: 0.85,
        ChunkType.PP: 0.7,
        ChunkType.ADJP: 0.65,
        ChunkType.ADVP: 0.6,
        ChunkType.MISC: 0.5,
    }
    for chunk in chunked.chunks:
        role_w = ROLE_WEIGHTS.get(chunk.dep_role, 0.5)
        type_w = TYPE_WEIGHTS.get(chunk.chunk_type, 0.5)
        chunk.context_weight = round((role_w + type_w) / 2, 3)
    return chunked
