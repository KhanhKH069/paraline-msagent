"""
services/api-gateway/routers/agent.py
Meeting agent REST endpoint — proxies to agent-service.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()
_http = httpx.AsyncClient(timeout=120.0)
AGENT_URL = os.getenv("AGENT_URL", "http://agent-service:8005")


@router.post("/summarize/{session_id}")
async def summarize_meeting(session_id: str):
    """Trigger meeting minutes generation for a completed session."""
    try:
        resp = await _http.post(f"{AGENT_URL}/agent/summarize/{session_id}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
