"""
services/agent-service/main.py
AI Meeting Agent — tóm tắt biên bản + Action Items.
Vexa pattern: MCP agent / post-meeting analysis.
LLM backend: Ollama (Llama 3 8B / Gemma 3 local).

POST /agent/summarize/{session_id}  →  MeetingMinutesResponse
"""
import json
import logging
import os
import re
import time
from typing import List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime

from prompts import SUMMARY_PROMPT, ACTION_ITEMS_PROMPT

logger = logging.getLogger("paraline.agent")

OLLAMA_HOST   = os.getenv("OLLAMA_HOST",  "http://ollama:11434")
LLM_MODEL     = os.getenv("LLM_MODEL",    "llama3:8b")
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://transcription-collector:8006")

_http = httpx.AsyncClient(timeout=120.0)
app = FastAPI(title="Paraline Agent Service")


class ActionItem(BaseModel):
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "medium"


class MeetingMinutesResp(BaseModel):
    session_id: str
    summary: str
    key_points: List[str] = []
    action_items: List[ActionItem] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_latency_ms: float = 0.0


@app.post("/agent/summarize/{session_id}", response_model=MeetingMinutesResp)
async def summarize(session_id: str):
    t0 = time.perf_counter()
    try:
        # Lấy full transcript từ collector
        resp = await _http.get(f"{COLLECTOR_URL}/sessions/{session_id}/export")
        resp.raise_for_status()
        transcript = resp.json().get("transcript", "")

        if not transcript.strip():
            raise HTTPException(404, "No transcript found for this session")

        # Gọi LLM song song: summary + action items
        summary_raw, actions_raw = await _run_parallel(transcript)

        summary, key_points = _parse_summary(summary_raw)
        action_items = _parse_actions(actions_raw)

        ms = (time.perf_counter() - t0) * 1000
        logger.info(f"Meeting minutes generated in {ms:.0f}ms for {session_id[:8]}")

        return MeetingMinutesResp(
            session_id=session_id,
            summary=summary,
            key_points=key_points,
            action_items=action_items,
            total_latency_ms=round(ms, 1),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


async def _run_parallel(transcript: str):
    """Chạy 2 LLM calls song song để tiết kiệm thời gian."""
    import asyncio
    summary_task = _call_llm(SUMMARY_PROMPT.format(transcript=transcript))
    actions_task = _call_llm(ACTION_ITEMS_PROMPT.format(transcript=transcript))
    return await asyncio.gather(summary_task, actions_task)


async def _call_llm(prompt: str) -> str:
    """Gọi Ollama generate API."""
    resp = await _http.post(f"{OLLAMA_HOST}/api/generate", json={
        "model":  LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024},
    })
    resp.raise_for_status()
    return resp.json().get("response", "")


def _parse_summary(raw: str):
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    summary = lines[0] if lines else raw.strip()
    key_points = [l.lstrip("-•* ").strip() for l in lines[1:] if l.startswith(("-", "•", "*", "–"))]
    return summary, key_points[:10]


def _parse_actions(raw: str) -> List[ActionItem]:
    try:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            items = json.loads(m.group())
            return [ActionItem(**item) for item in items if "task" in item]
    except Exception:
        pass
    return []


@app.get("/health")
async def health():
    return {"status": "ok", "llm": LLM_MODEL}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)
