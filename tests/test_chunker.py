"""
tests/test_chunker.py

Unit tests cho sentence chunker modules.
Chạy: pytest tests/test_chunker.py -v
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chunker.sentence_chunker import (
    ChunkType,
    ChunkItem,
    ChunkedSentence,
    assign_context_weights,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def make_fake_chunked(texts, types, roles) -> ChunkedSentence:
    chunks = []
    cursor = 0
    for text, ctype, role in zip(texts, types, roles):
        n = len(text.split())
        chunks.append(
            ChunkItem(
                text=text,
                chunk_type=ctype,
                start_token=cursor,
                end_token=cursor + n,
                position_ratio=cursor / max(sum(len(t.split()) for t in texts) - 1, 1),
                dep_role=role,
                head_text=text.split()[0],
                lang="en",
            )
        )
        cursor += n

    return ChunkedSentence(
        original=" ".join(texts),
        lang="en",
        tokens=" ".join(texts).split(),
        chunks=chunks,
    )


# ─── ChunkItem tests ──────────────────────────────────────────────────────────

def test_chunk_item_creation():
    item = ChunkItem(
        text="the red car",
        chunk_type=ChunkType.NP,
        start_token=0,
        end_token=3,
        position_ratio=0.0,
        dep_role="subj",
        head_text="car",
        lang="en",
    )
    assert item.text == "the red car"
    assert item.chunk_type == ChunkType.NP
    assert item.context_weight == 1.0  # default
    assert item.translated is None


def test_chunk_type_values():
    assert ChunkType.NP.value == "NP"
    assert ChunkType.VP.value == "VP"
    assert ChunkType.PP.value == "PP"
    assert ChunkType.SBAR.value == "SBAR"


# ─── ChunkedSentence tests ────────────────────────────────────────────────────

def test_chunked_sentence_chunk_texts():
    cs = make_fake_chunked(
        texts=["The team", "is working", "on the project"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.PP],
        roles=["subj", "root", "prep"],
    )
    assert cs.chunk_texts == ["The team", "is working", "on the project"]


def test_chunked_sentence_to_dict():
    cs = make_fake_chunked(
        texts=["Alice", "runs", "quickly"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.ADVP],
        roles=["subj", "root", "mod"],
    )
    d = cs.to_dict()
    assert "original" in d
    assert "chunks" in d
    assert len(d["chunks"]) == 3
    assert d["chunks"][0]["type"] == "NP"
    assert d["chunks"][1]["dep_role"] == "root"


# ─── Context weight assignment ────────────────────────────────────────────────

def test_assign_context_weights_ordering():
    """Subject và verb nên có weight cao hơn modifier."""
    cs = make_fake_chunked(
        texts=["The server", "crashed", "unexpectedly"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.ADVP],
        roles=["subj", "root", "mod"],
    )
    cs = assign_context_weights(cs)

    weights = {c.dep_role: c.context_weight for c in cs.chunks}
    # subj và root nên ≥ mod
    assert weights.get("subj", 0) >= weights.get("mod", 0)
    # root/VP cũng cao
    assert weights.get("root", 0) >= weights.get("mod", 0)


def test_assign_context_weights_range():
    """Tất cả weights phải trong [0.0, 1.0]."""
    cs = make_fake_chunked(
        texts=["A", "B", "C", "D"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.PP, ChunkType.MISC],
        roles=["subj", "obj", "prep", "misc"],
    )
    cs = assign_context_weights(cs)
    for c in cs.chunks:
        assert 0.0 <= c.context_weight <= 1.0, f"Weight out of range: {c}"


def test_context_weight_consistency():
    """ROOT type nên cho weight cao nhất."""
    cs = make_fake_chunked(
        texts=["Everything"],
        types=[ChunkType.ROOT],
        roles=["misc"],
    )
    cs = assign_context_weights(cs)
    assert cs.chunks[0].context_weight >= 0.7


# ─── VietnameseChunker regex fallback ─────────────────────────────────────────

def test_vietnamese_regex_chunker():
    """Test regex fallback khi spaCy model không có."""
    from src.chunker.sentence_chunker import VietnameseChunker

    # Patch để force regex mode
    chunker = VietnameseChunker.__new__(VietnameseChunker)
    chunker._use_regex = True

    text = "Tôi đang làm việc nhưng gặp vấn đề với máy chủ"
    result = chunker._regex_chunk(text)

    assert result.original == text
    assert result.lang == "vi"
    assert len(result.chunks) >= 1
    assert all(isinstance(c, ChunkItem) for c in result.chunks)


# ─── Position ratio ───────────────────────────────────────────────────────────

def test_position_ratio_first_last():
    """Chunk đầu tiên nên có position_ratio thấp nhất."""
    cs = make_fake_chunked(
        texts=["start word", "middle word", "end word"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.NP],
        roles=["subj", "root", "obj"],
    )
    ratios = [c.position_ratio for c in cs.chunks]
    assert ratios[0] <= ratios[-1]


# ─── Integration smoke test ───────────────────────────────────────────────────

def test_to_dict_all_fields_present():
    cs = make_fake_chunked(
        texts=["The API", "is returning", "an error"],
        types=[ChunkType.NP, ChunkType.VP, ChunkType.NP],
        roles=["subj", "root", "obj"],
    )
    cs = assign_context_weights(cs)
    d = cs.to_dict()

    required_chunk_keys = {"text", "type", "start", "end", "position_ratio", "dep_role", "head", "context_weight"}
    for chunk_dict in d["chunks"]:
        assert required_chunk_keys.issubset(set(chunk_dict.keys()))
