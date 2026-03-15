"""
services/admin-api/main.py
Admin API — quản lý server, xem sessions, stats.
Vexa pattern: admin-api service (port 8057).
"""
import os
import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

ADMIN_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
security = HTTPBearer()

app = FastAPI(title="Paraline Admin API", docs_url="/admin/docs")


def verify_admin(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds.credentials != ADMIN_TOKEN:
        raise HTTPException(403, "Forbidden")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "paraline-admin"}


@app.get("/admin/status", dependencies=[Depends(verify_admin)])
async def server_status():
    """Overview of all running services."""
    import httpx
    services = {
        "whisperlive":  "http://whisperlive:8001/health",
        "translation":  "http://translation-service:8002/health",
        "tts":          "http://tts-service:8003/health",
        "vision":       "http://vision-service:8004/health",
        "agent":        "http://agent-service:8005/health",
        "collector":    "http://transcription-collector:8006/health",
    }
    results = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in services.items():
            try:
                r = await client.get(url)
                results[name] = "ok" if r.ok else f"error {r.status_code}"
            except Exception:
                results[name] = "unreachable"
    return results


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8057)
