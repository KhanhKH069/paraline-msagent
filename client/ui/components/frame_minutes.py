import logging
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QApplication,
)

from client.ui.components.helpers import card, label

logger = logging.getLogger("meeting_ai.minutes")


class FrameMinutes(QWidget):
    """
    Tab Biên bản — tạo, hiển thị, sao chép và gửi tóm tắt cuộc họp & action items.
    """
    generate_requested = pyqtSignal()
    send_meet_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_data: dict = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # ── Action Toolbar ──
        tb = QHBoxLayout()
        tb.setSpacing(6)

        self._btn_generate = QPushButton("⚡ Tạo biên bản")
        self._btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_generate.setStyleSheet("""
            QPushButton {
                background: #00e5a0; border: none; border-radius: 6px;
                color: #111; font-size: 11px; font-weight: 800;
                padding: 6px 12px;
            }
            QPushButton:hover { background: #00c88c; }
            QPushButton:disabled { background: #e0e0e0; color: #888; }
        """)
        self._btn_generate.clicked.connect(self.generate_requested.emit)
        tb.addWidget(self._btn_generate)

        self._btn_copy = QPushButton("📋 Sao chép")
        self._btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_copy.setStyleSheet("""
            QPushButton {
                background: #f0fdf9; border: 1px solid rgba(0,229,160,0.4);
                border-radius: 6px; font-size: 11px; padding: 5px 10px; color: #007a50; font-weight: 600;
            }
            QPushButton:hover { background: #e0fbf2; }
            QPushButton:disabled { background: #f9f9f9; border-color: #eee; color: #bbb; }
        """)
        self._btn_copy.setEnabled(False)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        tb.addWidget(self._btn_copy)

        self._btn_send_meet = QPushButton("📤 Gửi vào Meet")
        self._btn_send_meet.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_send_meet.setStyleSheet("""
            QPushButton {
                background: #f0fdf9; border: 1px solid rgba(0,229,160,0.4);
                border-radius: 6px; font-size: 11px; padding: 5px 10px; color: #007a50; font-weight: 600;
            }
            QPushButton:hover { background: #e0fbf2; }
            QPushButton:disabled { background: #f9f9f9; border-color: #eee; color: #bbb; }
        """)
        self._btn_send_meet.setEnabled(False)
        self._btn_send_meet.clicked.connect(self._send_to_meet)
        tb.addWidget(self._btn_send_meet)

        tb.addStretch()
        lay.addLayout(tb)

        # ── Status info ──
        self._status_lbl = label("", "trans_src")
        self._status_lbl.hide()
        lay.addWidget(self._status_lbl)

        # ── Scroll Area for Minutes Content ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._inner = QWidget()
        self._inner_lay = QVBoxLayout(self._inner)
        self._inner_lay.setContentsMargins(4, 4, 4, 4)
        self._inner_lay.setSpacing(10)

        # Placeholder ban đầu
        self._placeholder = label("Bấm '⚡ Tạo biên bản' để AI tóm tắt nội dung cuộc họp và trích xuất các hành động cần làm.", "trans_src")
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inner_lay.addStretch()
        self._inner_lay.addWidget(self._placeholder)
        self._inner_lay.addStretch()

        scroll.setWidget(self._inner)
        lay.addWidget(scroll, 1)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_loading(self, is_loading: bool, msg: str = "⏳ Đang phân tích hội thoại và tạo biên bản bằng AI..."):
        """Bật/tắt trạng thái đang phân tích."""
        self._btn_generate.setEnabled(not is_loading)
        if is_loading:
            self._status_lbl.setText(msg)
            self._status_lbl.show()
        else:
            self._status_lbl.hide()

    def populate(self, data: dict):
        """Điền nội dung biên bản từ dict trả về từ server."""
        self._current_data = data
        self.set_loading(False)
        self._btn_copy.setEnabled(True)
        self._btn_send_meet.setEnabled(True)

        lay = self._inner_lay
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Tóm tắt
        lay.addWidget(label("TÓM TẮT NỘI DUNG CUỘC HỌP", "section_label"))
        summary_card = card("minutes_body")
        sc_lay = QVBoxLayout(summary_card)
        sc_lay.setContentsMargins(12, 10, 12, 10)
        summary_text = data.get("summary", "Không có tóm tắt.")
        summary_lbl = label(summary_text, "chat_text")
        summary_lbl.setWordWrap(True)
        summary_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sc_lay.addWidget(summary_lbl)
        lay.addWidget(summary_card)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(0,229,160,0.2); margin: 6px 0;")
        lay.addWidget(sep)

        # Action items
        action_items = data.get("action_items", [])
        if action_items:
            lay.addWidget(label(f"HÀNH ĐỘNG CẦN LÀM ({len(action_items)})", "section_label"))
            for item in action_items:
                self._add_action_item(lay, item)
        else:
            no_ai_lbl = label("Không phát hiện action item nào cần theo dõi.", "trans_src")
            no_ai_lbl.setStyleSheet("font-style: italic; color: #888;")
            lay.addWidget(no_ai_lbl)

        lay.addStretch()

    def set_empty(self, msg: str = "Chưa có dữ liệu biên bản họp."):
        self.clear()
        if self._placeholder:
            self._placeholder.setText(msg)

    def clear(self):
        self._current_data = {}
        self._btn_copy.setEnabled(False)
        self._btn_send_meet.setEnabled(False)
        self._status_lbl.hide()
        lay = self._inner_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if self._placeholder:
            self._placeholder.setText("Bấm '⚡ Tạo biên bản' để AI tóm tắt nội dung cuộc họp và trích xuất các hành động cần làm.")
            self._placeholder.show()
            lay.addStretch()
            lay.addWidget(self._placeholder)
            lay.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_as_text(self) -> str:
        if not self._current_data:
            return ""
        summary = self._current_data.get("summary", "")
        lines = [
            "📋 BIÊN BẢN CUỘC HỌP (Tóm tắt bởi AI)",
            "─────────────────────────────",
            summary,
            "",
            "📌 HÀNH ĐỘNG CẦN LÀM:",
        ]
        items = self._current_data.get("action_items", [])
        if items:
            for it in items:
                pri_raw = str(it.get("priority") or "med").lower()
                pri = "CAO" if pri_raw == "high" else ("THẤP" if pri_raw == "low" else "VỪA")
                task = it.get("task", "")
                who = it.get("assignee") or "Chưa phân công"
                lines.append(f"• [{pri}] {task} (Phụ trách: {who})")
        else:
            lines.append("• (Không có hành động cụ thể)")
        return "\n".join(lines)

    def _copy_to_clipboard(self):
        text = self._format_as_text()
        if not text:
            return
        cb = QApplication.clipboard()
        if cb:
            cb.setText(text)
            prev_text = self._btn_copy.text()
            self._btn_copy.setText("✅ Đã chép!")
            QTimer.singleShot(2000, lambda: self._btn_copy.setText(prev_text))

    def _send_to_meet(self):
        text = self._format_as_text()
        if text:
            self.send_meet_requested.emit(text)
            prev_text = self._btn_send_meet.text()
            self._btn_send_meet.setText("✅ Đã gửi!")
            QTimer.singleShot(2000, lambda: self._btn_send_meet.setText(prev_text))

    def _add_action_item(self, parent_lay, item: dict):
        ai = card("action_item")
        ai_lay = QHBoxLayout(ai)
        ai_lay.setContentsMargins(10, 8, 10, 8)
        ai_lay.setSpacing(8)

        pri = str(item.get("priority", "med")).lower()
        if pri == "high":
            pri_txt = "CAO"
            pri_cls = "pri_high"
        elif pri == "low":
            pri_txt = "THẤP"
            pri_cls = "pri_low"
        else:
            pri_txt = "VỪA"
            pri_cls = "pri_med"

        pri_lbl = label(pri_txt, pri_cls)
        ai_lay.addWidget(pri_lbl, 0, Qt.AlignmentFlag.AlignTop)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        task_lbl = label(item.get("task", ""), "chat_text")
        task_lbl.setWordWrap(True)
        task_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        assignee = item.get("assignee") or "Chưa phân công"
        who_lbl = label(f"👤 Phụ trách: {assignee}", "trans_src")

        txt_col.addWidget(task_lbl)
        txt_col.addWidget(who_lbl)
        ai_lay.addLayout(txt_col)

        parent_lay.addWidget(ai)