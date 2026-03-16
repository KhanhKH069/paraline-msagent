"""
client/meet_integration/bridge_server.py
HTTP Server siêu nhẹ (built-in) nhận event từ Chrome Extension.

Chạy ở port 9877 (mặc định).
"""
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger("paraline.meet_bridge")

BRIDGE_PORT = int(os.getenv("MEET_BRIDGE_PORT", "9877"))
MAX_QUEUE = int(os.getenv("MEET_CHAT_QUEUE_MAX", "200"))


class _BridgeRequestHandler(BaseHTTPRequestHandler):
    """Xử lý request từ Chrome Extension"""
    
    # Disable default logging to stdout
    def log_message(self, format, *args):
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        if self.path == "/poll":
            payload = self.server.dequeue_chat()
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return
            
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/event":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                    self.server.handle_event(data)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from extension")
            
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if self.path == "/enqueue":
            content_length = int(self.headers.get("Content-Length", 0))
            text = ""
            if content_length > 0:
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                    text = str(data.get("text", "")).strip()
                except json.JSONDecodeError:
                    text = ""

            ok = False
            if text:
                self.server.enqueue_chat(text)
                ok = True

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": ok}).encode("utf-8"))
            return
            
        self.send_response(404)
        self.end_headers()


class MeetBridgeServer:
    """
    Background thread chạy HTTP server để lắng nghe event từ Chrome Extension.
    Thay thế cho MeetingMonitor cũ (vốn dùng Graph API).
    """

    def __init__(
        self,
        on_meeting_started: Optional[Callable[[str], None]] = None,
        on_meeting_ended:   Optional[Callable[[], None]]    = None,
        port: int = BRIDGE_PORT
    ):
        self._on_started = on_meeting_started
        self._on_ended   = on_meeting_ended
        self._port       = port

        self._running    = False
        self._thread: Optional[threading.Thread] = None
        self._httpd: Optional[HTTPServer] = None
        
        self._meeting_active = False
        self._q_lock = threading.Lock()
        self._chat_q: deque[str] = deque()

    def is_enabled(self) -> bool:
        """Luôn bật (không phụ thuộc env nhiều như Teams)"""
        return True

    def start(self):
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True, name="MeetBridgeServer")
        self._thread.start()
        logger.info(f"MeetBridgeServer started on port {self._port}")

    def stop(self):
        self._running = False
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("MeetBridgeServer stopped")

    def _run_server(self):
        try:
            self._httpd = HTTPServer(("127.0.0.1", self._port), _BridgeRequestHandler)
            
            # Monkey-patch server để handler có thể gọi lại ra ngoài
            self._httpd.handle_event = self._on_extension_event
            self._httpd.enqueue_chat = self._enqueue_chat
            self._httpd.dequeue_chat = self._dequeue_chat
            
            self._httpd.serve_forever()
        except OSError as e:
            logger.error(f"Lỗi khởi động Bridge Server (port {self._port} có thể đang được dùng): {e}")

    def _on_extension_event(self, data: dict):
        event_type = data.get("type")
        
        if event_type == "meeting_started" and not self._meeting_active:
            url = data.get("meet_url", "https://meet.google.com/new")
            self._meeting_active = True
            logger.info(f"📢 Meet Bridge: Cuộc họp bắt đầu! url={url}")
            if self._on_started:
                self._on_started(url)
                
        elif event_type == "meeting_ended" and self._meeting_active:
            self._meeting_active = False
            logger.info("📴 Meet Bridge: Cuộc họp kết thúc!")
            if self._on_ended:
                self._on_ended()

    def _enqueue_chat(self, text: str):
        with self._q_lock:
            if len(self._chat_q) >= MAX_QUEUE:
                self._chat_q.popleft()
            self._chat_q.append(text)

    def _dequeue_chat(self) -> dict:
        with self._q_lock:
            if not self._chat_q:
                return {"ok": True, "has": False}
            text = self._chat_q.popleft()
            return {"ok": True, "has": True, "text": text}
