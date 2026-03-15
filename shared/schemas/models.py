"""
shared/schemas/models.py
Pydantic schemas dùng chung — client ↔ server ↔ tất cả services.
Vexa pattern: shared database models.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


# ─────────────────────────────────────────────
# Language Codes (NLLB format)
# ─────────────────────────────────────────────
class Lang(str, Enum):
    JA = "jpn_Jpan"
    EN = "eng_Latn"
    VI = "vie_Latn"


class Direction(str, Enum):
    INBOUND  = "inbound"   # Partner JP/EN → VN audio + subtitle
    OUTBOUND = "outbound"  # VMG staff VN/EN → text → Teams chat


class SessionStatus(str, Enum):
    ACTIVE   = "active"
    PAUSED   = "paused"
    FINISHED = "finished"


# ─────────────────────────────────────────────
# WebSocket Frame Schemas (client ↔ api-gateway)
# ─────────────────────────────────────────────

class AudioChunkFrame(BaseModel):
    """Client → Server: một chunk PCM audio (500ms)."""
    type: str = "audio_chunk"
    data: str                          # base64 float32 PCM
    src_lang: Lang = Lang.JA
    tgt_lang: Lang = Lang.VI
    session_id: str
    chunk_index: int = 0


class SubtitleFrame(BaseModel):
    """Server → Client: phụ đề realtime."""
    type: str = "subtitle"
    text: str
    latency_ms: float = 0.0


class InboundResultFrame(BaseModel):
    """Server → Client: TTS audio + subtitle (inbound pipeline)."""
    type: str = "inbound_result"
    original_text: str
    translated_text: str
    audio_b64: Optional[str] = None    # base64 WAV từ Piper TTS
    sample_rate: int = 22050
    latency_ms: float = 0.0


class OutboundResultFrame(BaseModel):
    """Server → Client: text đã dịch để push Teams chat (outbound pipeline)."""
    type: str = "outbound_result"
    original_text: str                 # Lời VMG staff
    translated_text: str               # Đã dịch → JP/EN
    tgt_lang: Lang = Lang.JA
    push_to_teams: bool = True
    latency_ms: float = 0.0


class ErrorFrame(BaseModel):
    """Server → Client: lỗi."""
    type: str = "error"
    message: str
    code: str = "INTERNAL_ERROR"


# ─────────────────────────────────────────────
# ASR Service
# ─────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    audio_b64: str
    language: Optional[str] = "ja"    # Whisper language code
    sample_rate: int = 16000
    vad_filter: bool = True


class TranscribeResponse(BaseModel):
    text: str
    language: str
    latency_ms: float
    segments: List[dict] = []


# ─────────────────────────────────────────────
# Translation Service
# ─────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"


class TranslateResponse(BaseModel):
    translated_text: str
    src_lang: str
    tgt_lang: str
    latency_ms: float


class BatchTranslateRequest(BaseModel):
    texts: List[str]
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"


class BatchTranslateResponse(BaseModel):
    translations: List[str]
    latency_ms: float


# ─────────────────────────────────────────────
# TTS Service
# ─────────────────────────────────────────────

class SynthRequest(BaseModel):
    text: str
    speed: float = 1.0


class SynthResponse(BaseModel):
    audio_b64: str       # base64 WAV
    sample_rate: int
    latency_ms: float


# ─────────────────────────────────────────────
# Vision Service (Image Translation)
# ─────────────────────────────────────────────

class ImageTranslateRequest(BaseModel):
    session_id: str
    image_b64: str
    src_lang: str = "jpn_Jpan"
    tgt_lang: str = "vie_Latn"
    font_auto_resize: bool = True


class OCRBlock(BaseModel):
    original_text: str
    translated_text: str = ""
    bbox: List[List[int]]   # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    confidence: float


class ImageTranslateResponse(BaseModel):
    translated_image_b64: str
    ocr_blocks: List[OCRBlock]
    total_latency_ms: float


# ─────────────────────────────────────────────
# Session & Meeting Models
# Vexa pattern: database meeting models
# ─────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    teams_meeting_id: Optional[str] = None
    teams_chat_id: Optional[str] = None
    inbound_src_lang: str = "jpn_Jpan"
    outbound_tgt_lang: str = "jpn_Jpan"


class SessionResponse(BaseModel):
    session_id: str
    status: SessionStatus
    created_at: datetime
    teams_chat_id: Optional[str] = None


class TranscriptSegment(BaseModel):
    """Lưu vào DB qua transcription-collector."""
    session_id: str
    segment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    direction: Direction
    original_text: str
    translated_text: str
    src_lang: str
    tgt_lang: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float = 0.0


# ─────────────────────────────────────────────
# Agent Service (Meeting Minutes)
# ─────────────────────────────────────────────

class ActionItem(BaseModel):
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "medium"


class MeetingMinutesResponse(BaseModel):
    session_id: str
    summary: str
    key_points: List[str] = []
    action_items: List[ActionItem] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_latency_ms: float = 0.0
