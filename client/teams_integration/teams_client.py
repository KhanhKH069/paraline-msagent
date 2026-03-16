"""
client/teams_integration/teams_client.py
Microsoft Teams Integration.

Mode 1: Incoming Webhook (simple, send-only, no Azure AD needed)
Mode 2: Microsoft Graph API (full: read + send, production-grade)

Auto-detect mode từ .env:
  TEAMS_CLIENT_ID set → Graph API mode
  TEAMS_WEBHOOK_URL set → Webhook mode
"""
import logging
import os
import subprocess
import time
import webbrowser
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger("paraline.teams")

WEBHOOK_URL   = os.getenv("TEAMS_WEBHOOK_URL",   "")
TENANT_ID     = os.getenv("TEAMS_TENANT_ID",     "")
CLIENT_ID     = os.getenv("TEAMS_CLIENT_ID",     "")
CLIENT_SECRET = os.getenv("TEAMS_CLIENT_SECRET", "")
BOT_TRIGGER   = "@VMG_Translator"


class TeamsClient:
    def __init__(self):
        self._mode          = self._detect_mode()
        self._token:   Optional[str]   = None
        self._token_exp: float         = 0
        self._chat_id: Optional[str]   = None
        self._last_msg_id: Optional[str] = None
        logger.info(f"Teams client mode: {self._mode}")

    def is_connected(self) -> bool:
        return self._mode != "none"

    def set_chat_id(self, chat_id: str):
        """Gọi sau khi detect được chat_id của cuộc họp hiện tại."""
        self._chat_id = chat_id
        logger.info(f"Teams chat_id set: {chat_id}")

    # ─────────────────────────────────────────────
    # Send translated text to Teams chat
    # ─────────────────────────────────────────────

    def send_translation(self, original: str, translated: str, tgt_lang: str = "JP") -> bool:
        """
        Gửi kết quả dịch vào Teams chat với format đẹp.
        Gọi từ UI main thread sau khi nhận outbound_result từ server.
        """
        flag = "🇯🇵" if tgt_lang.upper() in ("JP", "JA") else "🇬🇧"
        html = (
            f'<div style="border-left:3px solid #ff6b35;padding:6px 10px;margin:4px 0">'
            f'<b>🤖 Paraline MSAgent</b><br/>'
            f'{flag} <b>{translated}</b><br/>'
            f'<span style="color:#888;font-size:11px">🇻🇳 {original}</span>'
            f'</div>'
        )
        plain = f"[Paraline] {translated}  |  (VN: {original})"
        return self._send(plain, html)

    def send_raw(self, text: str) -> bool:
        return self._send(text)

    def send_welcome(self) -> bool:
        msg = (
            "🟠 **Paraline MSAgent** đã kết nối!\n"
            "- ✅ Inbound: JP/EN → 🇻🇳 (tai nghe + phụ đề)\n"
            "- ✅ Outbound: 🇻🇳 → JP/EN (text vào chat này)\n"
            "- 📸 Dịch slide: Chụp màn hình, paste vào app\n\n"
            "_Gõ `@VMG_Translator stop` để dừng_"
        )
        return self._send(msg)

    # ─────────────────────────────────────────────
    # Poll for @VMG_Translator commands
    # ─────────────────────────────────────────────

    def poll_command(self) -> Optional[str]:
        """
        Check Teams chat for @VMG_Translator start/stop commands.
        Returns: "start" | "stop" | None
        Called every 2s from UI timer.
        """
        if self._mode != "graph" or not self._chat_id:
            return None
        try:
            msgs = self._get_recent_messages(limit=3)
            for m in msgs:
                mid  = m.get("id", "")
                body = m.get("body", {}).get("content", "").lower()
                if mid == self._last_msg_id:
                    break
                self._last_msg_id = mid
                if f"{BOT_TRIGGER.lower()} start" in body:
                    return "start"
                if f"{BOT_TRIGGER.lower()} stop" in body:
                    return "stop"
        except Exception as e:
            logger.debug(f"Poll error: {e}")
        return None

    # ─────────────────────────────────────────────
    # Internal send
    # ─────────────────────────────────────────────

    def _send(self, plain: str, html: Optional[str] = None) -> bool:
        try:
            if self._mode == "webhook":
                return self._webhook_send(plain)
            elif self._mode == "graph":
                return self._graph_send(plain, html)
        except Exception as e:
            logger.error(f"Teams send error: {e}")
        return False

    def _webhook_send(self, text: str) -> bool:
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Paraline Translation",
            "sections": [{"activityTitle": "🟠 Paraline MSAgent", "activityText": text}],
        }
        r = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        return r.status_code == 200

    def _graph_send(self, plain: str, html: Optional[str] = None) -> bool:
        if not self._chat_id:
            logger.warning("No chat_id set for Graph API send")
            return False
        token = self._get_token()
        if not token:
            return False
        content_type = "html" if html else "text"
        content      = html or plain
        r = requests.post(
            f"https://graph.microsoft.com/v1.0/chats/{self._chat_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"body": {"contentType": content_type, "content": content}},
            timeout=10,
        )
        ok = r.status_code in (200, 201)
        if not ok:
            logger.error(f"Graph send {r.status_code}: {r.text[:200]}")
        return ok

    def _get_recent_messages(self, limit: int = 5) -> list:
        token = self._get_token()
        if not token or not self._chat_id:
            return []
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/chats/{self._chat_id}/messages?$top={limit}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return r.json().get("value", []) if r.ok else []

    def _get_token(self) -> Optional[str]:
        """OAuth2 client_credentials — cached until 60s before expiry."""
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = requests.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": CLIENT_ID,
                  "client_secret": CLIENT_SECRET, "scope": "https://graph.microsoft.com/.default"},
            timeout=10,
        )
        if r.ok:
            d = r.json()
            self._token    = d["access_token"]
            self._token_exp = time.time() + d.get("expires_in", 3600)
            return self._token
        logger.error(f"Token error: {r.text[:200]}")
        return None

    def _detect_mode(self) -> str:
        if CLIENT_ID and CLIENT_SECRET and TENANT_ID:
            return "graph"
        if WEBHOOK_URL:
            return "webhook"
        return "none"

    # ─────────────────────────────────────────────
    # Meeting Join / Leave (Windows deep link)
    # ─────────────────────────────────────────────

    def join_meeting(self, join_url: str) -> bool:
        """
        Tự động join Teams meeting.

        Cách làm:
        1. Thử mở qua protocol handler `msteams://` (Teams desktop app)
        2. Nếu thất bại hoặc không có Teams app → mở browser
        Returns True nếu lệnh được gởi thành công.
        """
        if not join_url:
            logger.warning("join_meeting: join_url trống")
            return False

        # Chuyển https:// link thành msteams:// deep link
        deep_link = join_url.replace(
            "https://teams.microsoft.com/",
            "msteams://",
        )
        # Encode lại spaces/special chars nếu cần
        if " " in deep_link:
            # Giữ scheme, encode phần còn lại
            scheme, rest = deep_link.split("://", 1)
            deep_link = f"{scheme}://{quote(rest, safe='/:@?=&%#')}"

        logger.info(f"Joining meeting via deep link: {deep_link[:80]}...")

        try:
            # Dùng `start` của Windows để trigger protocol handler
            subprocess.Popen(
                ["cmd", "/c", "start", "", deep_link],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            logger.info("✅ Teams meeting join command sent")
            return True
        except Exception as e:
            logger.warning(f"Deep link failed ({e}), fallback to browser")
            try:
                webbrowser.open(join_url)
                return True
            except Exception as e2:
                logger.error(f"Browser fallback also failed: {e2}")
                return False

    def leave_meeting(self):
        """
        Gửi Alt+Q vào cửa sổ Teams để leave meeting.
        Chỉ hoạt động nếu Teams window đang ở foreground hoặc dùng pywinauto.
        Hiện tại: log warning, không force kill process.
        """
        logger.info("leave_meeting: Yêu cầu kết thúc — user cần close meeting trên Teams")
        # TODO: nếu cần force leave, có thể dùng pywinauto để gửi phím vào Teams window

