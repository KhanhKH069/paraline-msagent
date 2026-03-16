"""
client/ui/main_app.py
Paraline MSAgent — PyQt6 Side-Panel GUI.

Thiết kế:
- Frameless window, dock sát phải màn hình bên cạnh Teams
- Luôn ở trên (Always-on-top)
- < 3000MB RAM
- Không che khuất cửa sổ Teams chính
"""
import io
import logging
import os
import sys
import uuid
from typing import Optional

import requests
from PIL import Image as PILImage
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QImage, QKeySequence, QPixmap, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget, QMenu,
    QSizeGrip, QSystemTrayIcon
)

from ..audio_router.audio_manager import AudioManager
from ..websocket_client.ws_client import ParalineWSClient
from ..teams_integration.teams_client import TeamsClient
from ..image_handler.image_handler import ImageHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("paraline.ui")

SERVER_WS   = os.getenv("PARALINE_SERVER_WS",   "ws://127.0.0.1:8765")
SERVER_REST = os.getenv("PARALINE_SERVER_REST",  "http://127.0.0.1:8056")
API_KEY     = os.getenv("CLIENT_API_KEY", "")

# ─────────────────────────────────────────────
# Stylesheet
# ─────────────────────────────────────────────
STYLE = """
* { font-family: 'Segoe UI', Arial, sans-serif; }

#panel {
    background: #12121f;
    border-left: 2px solid #ff6b35;
}

#title_label {
    color: #ff6b35;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#status_dot {
    font-size: 9px;
    padding: 2px 8px;
    border-radius: 8px;
    font-weight: 600;
}
#status_idle    { background: #2a2a3a; color: #888; }
#status_active  { background: #1a3a1a; color: #4caf50; }
#status_warning { background: #3a2a1a; color: #ff9800; }

QPushButton#btn_start {
    background: #ff6b35;
    color: #fff;
    border: none;
    padding: 8px 0;
    border-radius: 6px;
    font-weight: 700;
    font-size: 12px;
}
QPushButton#btn_start:hover  { background: #e05a25; }
QPushButton#btn_start:disabled { background: #555; color: #999; }

QPushButton#btn_stop {
    background: #c0392b;
    color: #fff;
    border: none;
    padding: 8px 0;
    border-radius: 6px;
    font-weight: 700;
    font-size: 12px;
}
QPushButton#btn_stop:hover { background: #a93226; }

QPushButton#btn_secondary {
    background: #1e1e35;
    color: #ccc;
    border: 1px solid #ff6b35;
    padding: 5px 0;
    border-radius: 5px;
    font-size: 11px;
}
QPushButton#btn_secondary:hover { background: #2a2a45; color: #ff6b35; }

#subtitle_area {
    background: #1a1a2e;
    color: #e8e8f0;
    font-size: 12px;
    border: 1px solid #2a2a4a;
    border-radius: 5px;
    padding: 4px;
}

#outbound_log {
    background: #0f0f1e;
    color: #90caf9;
    font-size: 11px;
    border: 1px solid #1e2a4a;
    border-radius: 4px;
}

#image_drop {
    background: #1a1a2e;
    color: #666;
    border: 2px dashed #2a3a5a;
    border-radius: 8px;
    font-size: 11px;
}

#section_label {
    color: #555;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}

#latency_label {
    color: #4caf50;
    font-size: 10px;
}
"""


class SubtitleWidget(QTextEdit):
    """Rolling subtitle display — shows last N translations."""
    MAX_LINES = 20

    def __init__(self):
        super().__init__()
        self.setObjectName("subtitle_area")
        self.setReadOnly(True)
        self.setMaximumHeight(150)
        self.setPlaceholderText("Phụ đề xuất hiện ở đây khi cuộc họp bắt đầu...")
        self._lines = []

    def add_line(self, text: str, latency_ms: float = 0):
        if not text.strip():
            return
        lat = f" [{latency_ms:.0f}ms]" if latency_ms > 0 else ""
        self._lines.append(f"{text}{lat}")
        if len(self._lines) > self.MAX_LINES:
            self._lines.pop(0)
        self.setPlainText("\n".join(self._lines))
        # Auto-scroll to bottom
        sb = self.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())


class ImagePanel(QWidget):
    """Drag-and-drop / Ctrl+V image translation panel."""
    translate_requested = pyqtSignal(object)  # PIL Image

    def __init__(self):
        super().__init__()
        self.setObjectName("image_drop")
        self.setMinimumHeight(120)
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self._label = QLabel("📸 Ctrl+V để dán ảnh slide\nhoặc kéo thả vào đây")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._img_display = QLabel()
        self._img_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_display.hide()
        layout.addWidget(self._img_display)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # Indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

    def show_input(self, pil_img):
        self._label.setText("⏳ Đang dịch slide...")
        self._progress.show()
        self._img_display.hide()

    def show_result(self, pil_img):
        self._progress.hide()
        self._label.setText("✅ Slide đã dịch (click để zoom)")
        # Scale to fit
        qimg = self._pil_to_qimage(pil_img)
        pm   = QPixmap.fromImage(qimg).scaledToWidth(260, Qt.TransformationMode.SmoothTransformation)
        self._img_display.setPixmap(pm)
        self._img_display.show()

    def show_error(self, msg: str):
        self._progress.hide()
        self._label.setText(f"❌ Lỗi: {msg}")

    @staticmethod
    def _pil_to_qimage(pil_img) -> QImage:
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        qimg = QImage()
        qimg.loadFromData(buf.getvalue())
        return qimg

    def dragEnterEvent(self, a0):
        if a0 is not None:
            mime = a0.mimeData()
            if mime is not None and mime.hasImage():
                a0.acceptProposedAction()

    def dropEvent(self, a0):
        if a0 is not None:
            mime = a0.mimeData()
            if mime is not None and mime.hasImage():
                qimg = mime.imageData()
                if isinstance(qimg, QImage):
                    self._emit_from_qimage(qimg)

    def _emit_from_qimage(self, qimg: QImage):
        buf = io.BytesIO()
        ptr = qimg.bits()
        if ptr is not None:
            ba  = ptr.asarray(qimg.sizeInBytes())
            PILImage.frombytes("RGBA", (qimg.width(), qimg.height()), bytes(ba), "raw", "BGRA").save(buf, "PNG")
            pil = PILImage.open(io.BytesIO(buf.getvalue())).convert("RGB")
            self.translate_requested.emit(pil)


class ParalineMainWindow(QMainWindow):
    """Side-panel window — always-on-top, docked right side of screen."""

    # Signals from background threads → UI thread
    sig_subtitle      = pyqtSignal(str, float)
    sig_outbound_text = pyqtSignal(str, str)
    sig_tts_audio     = pyqtSignal(str)
    sig_img_result    = pyqtSignal(object)
    sig_img_error     = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.session_id: Optional[str] = None
        self.ws_client:  Optional[ParalineWSClient] = None
        self.audio_mgr   = AudioManager()
        self.teams_client = TeamsClient()
        self.image_handler: Optional[ImageHandler] = None

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._setup_hotkeys()
        self._setup_tray()

        # Teams command polling
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_teams)
        self._poll_timer.start(2000)

    # ─────────────────────────────────────────────
    # Window setup
    # ─────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("Paraline MSAgent")
        self.setStyleSheet(STYLE)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool,
        )
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.geometry()
            W, H = 300, geom.height() - 80
            self.setGeometry(geom.width() - W - 8, 40, W, H)
        self.setMinimumWidth(260)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("panel")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── Header ───────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("🟠 Paraline MSAgent")
        title.setObjectName("title_label")
        self._status_dot = QLabel("● IDLE")
        self._status_dot.setObjectName("status_dot")
        self._status_dot.setProperty("class", "status_idle")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("background:transparent;color:#555;font-size:14px;border:none;")
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._status_dot)
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        # ── Divider ──────────────────────────────────────
        layout.addWidget(self._divider())

        # ── Session Buttons ───────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("▶  Bắt đầu Phiên dịch")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.clicked.connect(self._start_session)

        self._btn_stop = QPushButton("⏹  Kết thúc")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.clicked.connect(self._stop_session)
        self._btn_stop.setEnabled(False)

        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        layout.addLayout(btn_row)

        # ── Latency display ───────────────────────────────
        self._latency_label = QLabel("latency: —")
        self._latency_label.setObjectName("latency_label")
        layout.addWidget(self._latency_label)

        layout.addWidget(self._divider())

        # ── Subtitle section ──────────────────────────────
        layout.addWidget(self._section("📝 PHIÊN DỊCH THỜI GIAN THỰC"))
        self._subtitle = SubtitleWidget()
        layout.addWidget(self._subtitle)

        layout.addWidget(self._divider())

        # ── Image translation section ─────────────────────
        layout.addWidget(self._section("📸 DỊCH SLIDE (Ctrl+V)"))
        self._img_panel = ImagePanel()
        self._img_panel.translate_requested.connect(self._on_image_paste)
        layout.addWidget(self._img_panel)

        layout.addWidget(self._divider())

        # ── Outbound log section ──────────────────────────
        layout.addWidget(self._section("💬 ĐÃ ĐẨY VÀO TEAMS"))
        self._outbound_log = QTextEdit()
        self._outbound_log.setObjectName("outbound_log")
        self._outbound_log.setReadOnly(True)
        self._outbound_log.setMaximumHeight(90)
        layout.addWidget(self._outbound_log)

        layout.addStretch()

        # ── Footer ───────────────────────────────────────
        footer = QLabel("VMG_STAFF · 100% Offline")
        footer.setStyleSheet("color:#333; font-size:9px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        layout.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

    def _connect_signals(self):
        self.sig_subtitle.connect(self._on_subtitle)
        self.sig_outbound_text.connect(self._on_outbound_text)
        self.sig_tts_audio.connect(self._on_tts_audio)
        self.sig_img_result.connect(self._img_panel.show_result)
        self.sig_img_error.connect(self._img_panel.show_error)

    def _setup_hotkeys(self):
        QShortcut(QKeySequence("Ctrl+V"),         self, self._handle_paste)
        QShortcut(QKeySequence("Ctrl+Shift+P"),   self, self._toggle_visibility)

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        menu = QMenu()
        menu.addAction("Mở Paraline", self.show)
        menu.addSeparator()
        app_instance = QApplication.instance()
        if app_instance is not None:
            menu.addAction("Thoát", app_instance.quit)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("Paraline MSAgent")
        self._tray.show()

    # ─────────────────────────────────────────────
    # Session lifecycle
    # ─────────────────────────────────────────────

    def _start_session(self):
        self.session_id = str(uuid.uuid4())
        self.image_handler = ImageHandler(self.session_id, API_KEY)

        self.ws_client = ParalineWSClient(
            server_ws_url=SERVER_WS,
            session_id=self.session_id,
            api_key=API_KEY,
            on_subtitle=      lambda t, ms: self.sig_subtitle.emit(t, ms),
            on_inbound_audio= lambda b64:   self.sig_tts_audio.emit(b64),
            on_outbound_text= lambda o, t:  self.sig_outbound_text.emit(o, t),
        )
        self.ws_client.start()
        self.audio_mgr.start(
            inbound_cb=self.ws_client.send_inbound_chunk,
            outbound_cb=self.ws_client.send_outbound_chunk,
        )

        self._set_status("active", "● ACTIVE")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self.teams_client.send_welcome()
        logger.info(f"Session started: {self.session_id[:8]}")

    def _stop_session(self):
        if self.ws_client:
            self.ws_client.stop()
        self.audio_mgr.stop()

        self._set_status("warning", "● FINISHING")
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

        # Request meeting minutes after short delay
        QTimer.singleShot(1000, self._get_meeting_minutes)

    def _get_meeting_minutes(self):
        if not self.session_id:
            return
        try:
            r = requests.post(
                f"{SERVER_REST}/agent/summarize/{self.session_id}",
                timeout=90,
            )
            if r.ok:
                data = r.json()
                self._show_minutes(data)
        except Exception as e:
            logger.error(f"Meeting minutes error: {e}")
        finally:
            self._set_status("idle", "● IDLE")

    def _show_minutes(self, data: dict):
        summary = data.get("summary", "")
        items   = data.get("action_items", [])
        msg = f"📋 **Biên bản họp**\n\n{summary}\n\n"
        if items:
            msg += "✅ **Action Items:**\n"
            for item in items:
                msg += f"• [{item.get('priority','').upper()}] {item.get('task','')} — {item.get('assignee','?')}\n"
        self.teams_client.send_raw(msg)
        self._subtitle.add_line("✅ Đã gửi biên bản họp vào Teams")

    # ─────────────────────────────────────────────
    # Signal handlers
    # ─────────────────────────────────────────────

    def _on_subtitle(self, text: str, latency_ms: float):
        self._subtitle.add_line(text, latency_ms)
        self._latency_label.setText(f"latency: {latency_ms:.0f}ms")

    def _on_outbound_text(self, original: str, translated: str):
        self._outbound_log.append(f"→ {translated}")
        sb = self._outbound_log.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())
        self.teams_client.send_translation(original, translated)

    def _on_tts_audio(self, audio_b64: str):
        self.audio_mgr.play_tts(audio_b64)

    def _on_image_paste(self, pil_img):
        if not self.session_id:
            self._subtitle.add_line("⚠️ Cần bắt đầu phiên trước khi dịch ảnh")
            return
        self._img_panel.show_input(pil_img)
        if self.image_handler:
            self.image_handler.translate_image(
                pil_img,
                on_success=lambda img, blocks: self.sig_img_result.emit(img),
                on_error=  lambda msg:         self.sig_img_error.emit(msg),
            )

    # ─────────────────────────────────────────────
    # Teams polling
    # ─────────────────────────────────────────────

    def _poll_teams(self):
        cmd = self.teams_client.poll_command()
        if cmd == "start" and not self.session_id:
            self._start_session()
        elif cmd == "stop" and self.session_id:
            self._stop_session()

    # ─────────────────────────────────────────────
    # Utils
    # ─────────────────────────────────────────────

    def _handle_paste(self):
        from PyQt6.QtWidgets import QApplication as _App
        clipboard = _App.clipboard()
        if clipboard is not None:
            mime = clipboard.mimeData()
            if mime is not None and mime.hasImage():
                qimg = clipboard.image()
                if qimg is not None and not qimg.isNull():
                    ptr = qimg.bits()
                    if ptr is not None:
                        ba  = ptr.asarray(qimg.sizeInBytes())
                        pil = PILImage.frombytes("RGBA", (qimg.width(), qimg.height()), bytes(ba), "raw", "BGRA").convert("RGB")
                        self._on_image_paste(pil)

    def _toggle_visibility(self):
        self.hide() if self.isVisible() else self.show()

    def _set_status(self, state: str, text: str):
        self._status_dot.setText(text)
        self._status_dot.setObjectName(f"status_{state}")
        style = self._status_dot.style()
        if style is not None:
            style.unpolish(self._status_dot)
            style.polish(self._status_dot)

    @staticmethod
    def _divider() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color: #1e1e35;")
        return f

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("section_label")
        return lbl

    # Drag frameless window
    def mousePressEvent(self, a0):
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = a0.globalPosition().toPoint()

    def mouseMoveEvent(self, a0):
        if a0 is not None and a0.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(self.pos() + a0.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = a0.globalPosition().toPoint()


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Paraline MSAgent")
    window = ParalineMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
