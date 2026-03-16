"""
client/teams_integration/meeting_monitor.py
Teams Meeting Monitor — tự động detect cuộc họp bắt đầu/kết thúc
trong một channel chỉ định qua Microsoft Graph API.

Flow:
  poll → GET /teams/{team_id}/channels/{channel_id}/messages
       → detect callStartedEventMessageDetail → emit on_meeting_started(join_url)
       → detect callEndedEventMessageDetail   → emit on_meeting_ended()

Env vars cần có:
  TEAMS_TENANT_ID, TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET  (OAuth2 client_credentials)
  TEAMS_TEAM_ID       — ID của Team chứa channel
  TEAMS_CHANNEL_ID    — ID của channel dành riêng cho cuộc họp
  TEAMS_POLL_INTERVAL — giây giữa 2 lần poll (mặc định 10)
"""
import logging
import os
import threading
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger("paraline.meeting_monitor")

TENANT_ID     = os.getenv("TEAMS_TENANT_ID",     "")
CLIENT_ID     = os.getenv("TEAMS_CLIENT_ID",     "")
CLIENT_SECRET = os.getenv("TEAMS_CLIENT_SECRET", "")
TEAM_ID       = os.getenv("TEAMS_TEAM_ID",       "")
CHANNEL_ID    = os.getenv("TEAMS_CHANNEL_ID",    "")
POLL_INTERVAL = int(os.getenv("TEAMS_POLL_INTERVAL", "10"))

# Graph API event types cho call
_TYPE_CALL_STARTED = "#microsoft.graph.callStartedEventMessageDetail"
_TYPE_CALL_ENDED   = "#microsoft.graph.callEndedEventMessageDetail"


class MeetingMonitor:
    """
    Background thread poll Graph API để detect meeting bắt đầu / kết thúc.

    Sử dụng:
        monitor = MeetingMonitor(
            on_meeting_started=lambda url: ...,
            on_meeting_ended=lambda: ...,
        )
        monitor.start()
        ...
        monitor.stop()
    """

    def __init__(
        self,
        on_meeting_started: Optional[Callable[[str], None]] = None,
        on_meeting_ended:   Optional[Callable[[], None]]    = None,
    ):
        self._on_started = on_meeting_started
        self._on_ended   = on_meeting_ended

        self._running         = False
        self._thread: Optional[threading.Thread] = None

        # Token cache
        self._token:     Optional[str] = None
        self._token_exp: float         = 0

        # Trạng thái cuộc họp hiện tại
        self._meeting_active  = False
        self._last_message_id: Optional[str] = None

        # Kiểm tra config
        self._enabled = bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET
                             and TEAM_ID and CHANNEL_ID)
        if not self._enabled:
            logger.warning(
                "MeetingMonitor disabled — thiếu TEAMS_TENANT_ID / CLIENT_ID / "
                "CLIENT_SECRET / TEAM_ID / CHANNEL_ID trong .env"
            )

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def is_enabled(self) -> bool:
        return self._enabled

    def start(self):
        if not self._enabled:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True, name="MeetingMonitor")
        self._thread.start()
        logger.info(f"MeetingMonitor started — polling every {POLL_INTERVAL}s")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            assert self._thread is not None
            self._thread.join(timeout=5)
        logger.info("MeetingMonitor stopped")

    # ─────────────────────────────────────────────
    # Poll loop
    # ─────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                self._check_channel()
            except Exception as e:
                logger.error(f"MeetingMonitor poll error: {e}")
            # Sleep chia nhỏ để stop() không bị block lâu
            for _ in range(POLL_INTERVAL * 2):
                if not self._running:
                    return
                time.sleep(0.5)

    def _check_channel(self):
        """Lấy messages mới nhất, tìm call started/ended event."""
        msgs = self._get_channel_messages(limit=5)
        if not msgs:
            return

        # Graph trả về newest-first
        newest_id = msgs[0].get("id", "")

        # Nếu không có gì mới, bỏ qua
        if newest_id == self._last_message_id:
            return

        # Xử lý từng message mới (dừng khi gặp ID đã xử lý)
        for msg in msgs:
            mid = msg.get("id", "")
            if mid == self._last_message_id:
                break

            event_type = (
                msg.get("eventDetail", {}).get("@odata.type", "")
                if msg.get("eventDetail") else ""
            )

            if event_type == _TYPE_CALL_STARTED and not self._meeting_active:
                join_url = self._extract_join_url(msg)
                if join_url:
                    self._meeting_active = True
                    logger.info(f"📢 Meeting bắt đầu! join_url={join_url[:60]}...")
                    if self._on_started:
                        self._on_started(join_url)

            elif event_type == _TYPE_CALL_ENDED and self._meeting_active:
                self._meeting_active = False
                logger.info("📴 Meeting kết thúc!")
                if self._on_ended:
                    self._on_ended()

        self._last_message_id = newest_id

    # ─────────────────────────────────────────────
    # Graph API helpers
    # ─────────────────────────────────────────────

    def _get_channel_messages(self, limit: int = 5) -> list:
        token = self._get_token()
        if not token:
            return []
        url = (
            f"https://graph.microsoft.com/v1.0"
            f"/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages"
            f"?$top={limit}&$orderby=createdDateTime+desc"
        )
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if not r.ok:
            logger.error(f"Graph channel messages error {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("value", [])

    def _extract_join_url(self, msg: dict) -> Optional[str]:
        """
        Trích join URL từ channel message.
        Thử các trường phổ biến mà Graph trả về.
        """
        # Thử eventDetail trực tiếp
        event = msg.get("eventDetail", {}) or {}
        url = event.get("joinWebUrl") or event.get("joinMeetingIdSettings", {}).get("joinWebUrl")
        if url:
            return url

        # Thử body HTML — Teams thường nhúng link join trong body
        body_content = msg.get("body", {}).get("content", "")
        if "https://teams.microsoft.com/l/meetup-join/" in body_content:
            start = body_content.find("https://teams.microsoft.com/l/meetup-join/")
            end   = body_content.find('"', start)
            if end == -1:
                end = body_content.find("'", start)
            if end > start:
                return body_content[start:end]

        # Thử attachments
        for att in msg.get("attachments", []):
            att_url = att.get("content", "")
            if "meetup-join" in att_url:
                i = att_url.find("https://teams.microsoft.com")
                if i >= 0:
                    j = att_url.find('"', i)
                    if j == -1:
                        j = att_url.find("'", i)
                    return att_url[i:j] if j > i else None

        logger.warning("Không tìm thấy join URL trong message, dùng channel link fallback")
        return self._build_channel_meeting_link()

    def _build_channel_meeting_link(self) -> str:
        """Fallback: tạo deep link tới channel để user tự join."""
        return f"https://teams.microsoft.com/l/channel/{CHANNEL_ID}/meeting"

    def _get_token(self) -> Optional[str]:
        """OAuth2 client_credentials — cached until 60s before expiry."""
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = requests.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope":         "https://graph.microsoft.com/.default",
            },
            timeout=10,
        )
        if r.ok:
            d = r.json()
            self._token     = d["access_token"]
            self._token_exp = time.time() + d.get("expires_in", 3600)
            return self._token
        logger.error(f"MeetingMonitor token error: {r.text[:200]}")
        return None
