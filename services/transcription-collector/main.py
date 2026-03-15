"""
services/transcription-collector/main.py
Thu gom và lưu transcript segments vào PostgreSQL.
Vexa pattern: transcription-collector.

POST /segments     →  lưu một segment
GET  /segments/{session_id}  →  lấy toàn bộ transcript
GET  /sessions/{id}/export   →  export transcript dạng text
"""
import logging
import os
from datetime import datetime
from typing import List, Optional

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uuid

logger = logging.getLogger("paraline.collector")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://paraline:paraline@postgres:5432/paraline")

app = FastAPI(title="Paraline Transcription Collector")
_pool: Optional[asyncpg.Pool] = None


@app.on_event("startup")
async def startup():
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("✅ Database pool connected")


@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()


class SegmentIn(BaseModel):
    session_id: str
    direction: str
    original_text: str
    translated_text: str
    src_lang: str
    tgt_lang: str
    latency_ms: float = 0.0


class SegmentOut(BaseModel):
    segment_id: str
    session_id: str
    direction: str
    original_text: str
    translated_text: str
    src_lang: str
    tgt_lang: str
    timestamp: datetime
    latency_ms: float


@app.post("/segments", status_code=201)
async def store_segment(seg: SegmentIn):
    seg_id = str(uuid.uuid4())
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO transcript_segments
              (segment_id, session_id, direction, original_text, translated_text,
               src_lang, tgt_lang, latency_ms, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
        """, seg_id, seg.session_id, seg.direction,
             seg.original_text, seg.translated_text,
             seg.src_lang, seg.tgt_lang, seg.latency_ms)
    return {"segment_id": seg_id}


@app.get("/segments/{session_id}", response_model=List[SegmentOut])
async def get_segments(session_id: str):
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM transcript_segments
            WHERE session_id = $1
            ORDER BY created_at ASC
        """, session_id)
    return [dict(r) for r in rows]


@app.get("/sessions/{session_id}/export")
async def export_transcript(session_id: str, fmt: str = "text"):
    """Export transcript cho AI Agent xử lý."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT direction, translated_text, original_text, created_at
            FROM transcript_segments
            WHERE session_id = $1
            ORDER BY created_at ASC
        """, session_id)

    lines = []
    for r in rows:
        speaker = "🔵 Đối tác" if r["direction"] == "inbound" else "🟠 VMG"
        time_str = r["created_at"].strftime("%H:%M:%S")
        lines.append(f"[{time_str}] {speaker}: {r['translated_text']}")

    return {"session_id": session_id, "transcript": "\n".join(lines), "count": len(rows)}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8006)
