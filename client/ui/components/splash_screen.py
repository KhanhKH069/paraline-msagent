import subprocess
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QComboBox,
)

from client.ui.components.helpers import card, label
from client.ui.components.pulse_dot import PulseDot


def _get_pactl_sources() -> list[tuple[str, str]]:
    """
    Trả về list các PulseAudio/PipeWire sources dưới dạng (display_label, source_name).
    Chạy `pactl list sources short` và parse output.
    Monitor sources (*.monitor) được đánh dấu 🔊 để dễ nhận biết.
    """
    results = []
    try:
        out = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=3,
        )
        for line in out.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[1].strip()
                is_monitor = name.endswith(".monitor")
                icon = "🔊" if is_monitor else "🎙"
                display_name = name
                # Truncate if too long to prevent combo box spilling
                if len(display_name) > 35:
                    display_name = display_name[:16] + "..." + display_name[-16:]
                results.append((f"{icon} {display_name}", name))
    except Exception:
        pass
    return results


class SplashScreen(QWidget):
    """Màn hình đầu tiên: logo + chọn nền tảng + chọn thiết bị âm thanh + nhập link."""

    join_requested = pyqtSignal(str, str, str)   # (url, platform, device_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._platform = "meet"
        self._build()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 32)
        lay.setSpacing(0)

        lay.addStretch(2)

        # Pulse dot
        pulse_wrap = QWidget()
        pw_lay = QHBoxLayout(pulse_wrap)
        pw_lay.setContentsMargins(0, 0, 0, 0)
        pw_lay.addStretch()
        pw_lay.addWidget(PulseDot())
        pw_lay.addStretch()
        lay.addWidget(pulse_wrap)

        lay.addSpacing(20)

        # Brand name "Meeting" + "AI"
        brand_row = QWidget()
        br_lay = QHBoxLayout(brand_row)
        br_lay.setContentsMargins(0, 0, 0, 0)
        br_lay.setSpacing(0)
        br_lay.addStretch()
        br_lay.addWidget(label("Meeting ", "brand_main"))
        br_lay.addWidget(label("AI", "brand_accent"))
        br_lay.addStretch()
        lay.addWidget(brand_row)

        lay.addSpacing(6)

        tagline = label("ASSISTANT · REAL-TIME TRANSLATION", "brand_tagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(tagline)

        lay.addStretch(1)

        # Link card
        lcard = card("link_card")
        cl = QVBoxLayout(lcard)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(10)

        cl.addWidget(label("CHỌN NỀN TẢNG", "lc_label"))

        plat_row = QHBoxLayout()
        plat_row.setSpacing(6)
        self._btn_meet  = QPushButton("Google Meet")
        self._btn_teams = QPushButton("Teams")
        for btn in (self._btn_meet, self._btn_teams):
            btn.setObjectName("btn_platform")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_meet.setObjectName("btn_platform_active")
        self._btn_meet.clicked.connect(lambda: self._select("meet"))
        self._btn_teams.clicked.connect(lambda: self._select("teams"))
        plat_row.addWidget(self._btn_meet)
        plat_row.addWidget(self._btn_teams)
        cl.addLayout(plat_row)

        # ── Audio device selector ─────────────────────────────────────────
        cl.addWidget(label("THIẾT BỊ ĐẦU VÀO  (ưu tiên CABLE Output / Loa ảo)", "lc_label"))

        dev_row = QHBoxLayout()
        dev_row.setSpacing(6)

        self._combo_device = QComboBox()
        self._combo_device.setObjectName("combo_lang")
        
        # Cho phép viền bo tròn của khung dropdown
        self._combo_device.view().window().setWindowFlags(
            Qt.WindowType.Popup | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.NoDropShadowWindowHint
        )
        self._combo_device.view().window().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._combo_device.setToolTip(
            "🔊 CABLE Output / Monitor = Thu âm thanh cuộc họp (Google Meet / Teams)\n"
            "🎙 Microphone = Thu âm micro của bạn"
        )
        self._populate_devices()
        dev_row.addWidget(self._combo_device, 1)

        btn_refresh = QPushButton("🔄")
        btn_refresh.setObjectName("btn_go")
        btn_refresh.setFixedWidth(36)
        btn_refresh.setToolTip("Quét lại danh sách thiết bị")
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.clicked.connect(self._refresh_devices)
        cl.addLayout(dev_row)

        hint_lbl = label("💡 Test mic: chọn Microphone · Thu Meet: chọn CABLE Output hoặc Stereo Mix", "lc_hint")
        hint_lbl.setWordWrap(True)
        cl.addWidget(hint_lbl)
        # ─────────────────────────────────────────────────────────────────

        cl.addWidget(label("LINK CUỘC HỌP", "lc_label"))

        inp_row = QHBoxLayout()
        inp_row.setSpacing(8)
        self._inp = QLineEdit()
        self._inp.setObjectName("link_input")
        self._inp.setPlaceholderText("Dán link Google Meet vào đây…")
        self._inp.returnPressed.connect(self._emit_join)
        btn_go = QPushButton("Vào →")
        btn_go.setObjectName("btn_go")
        btn_go.setFixedWidth(70)
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.clicked.connect(self._emit_join)
        inp_row.addWidget(self._inp)
        inp_row.addWidget(btn_go)
        cl.addLayout(inp_row)

        lay.addWidget(lcard)
        lay.addStretch(2)

    # ── Device helpers ────────────────────────────────────────────────────────

    def _populate_devices(self):
        """Quét và làm sạch danh sách thiết bị âm thanh, tự động chọn thiết bị tốt nhất."""
        self._combo_device.clear()

        added = 0
        best_index = 0

        # --- 1. PulseAudio / PipeWire sources (Linux) ---
        pa_sources = _get_pactl_sources()
        if pa_sources:
            for idx, (lbl, name) in enumerate(pa_sources):
                self._combo_device.addItem(lbl, userData=("pulse", name))
                if ".monitor" in name.lower() or "virtual" in name.lower():
                    best_index = idx
                added += 1

        # --- 2. Fallback cho Windows / macOS / Linux không có pactl ---
        if not pa_sources:
            try:
                from client.audio_router.get_device import get_clean_input_devices
                clean_devs = get_clean_input_devices()
                for idx, (dev_idx, dev_info, host_api, icon, tag) in enumerate(clean_devs):
                    dname = dev_info["name"]
                    short_tag = ""
                    if "cable" in dname.lower():
                        short_tag = " [Thu Meet/Teams]"
                    elif "stereo mix" in dname.lower():
                        short_tag = " [Loa máy tính]"
                    elif "mic" in dname.lower():
                        short_tag = " [Micro bạn nói]"

                    display_text = f"{icon} {dname}{short_tag}"
                    if len(display_text) > 42:
                        display_text = display_text[:39] + "..."

                    self._combo_device.addItem(
                        display_text,
                        userData=("idx", str(dev_idx)),
                    )
                    self._combo_device.setItemData(
                        idx,
                        f"ID: {dev_idx} | {tag} | {host_api} | {dev_info['max_input_channels']}ch",
                        Qt.ItemDataRole.ToolTipRole,
                    )
                    # Tự động ưu tiên chọn CABLE Output
                    if "cable" in dname.lower() or "monitor" in dname.lower():
                        best_index = idx
                    added += 1
            except Exception:
                pass

        if added == 0:
            self._combo_device.addItem("— Không tìm thấy thiết bị thu âm nào —", userData=("", ""))
        else:
            self._combo_device.setCurrentIndex(best_index)

    def _refresh_devices(self):
        self._populate_devices()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _select(self, plat: str):
        self._platform = plat
        self._btn_meet.setObjectName("btn_platform_active" if plat == "meet" else "btn_platform")
        self._btn_teams.setObjectName("btn_platform_active" if plat == "teams" else "btn_platform")
        for btn in (self._btn_meet, self._btn_teams):
            s = btn.style()
            if s: s.unpolish(btn); s.polish(btn)
        self._inp.setPlaceholderText(
            "Dán link Google Meet vào đây…" if plat == "meet"
            else "Dán link Microsoft Teams vào đây…"
        )

    def _emit_join(self):
        url = self._inp.text().strip()
        if not url:
            self._inp.setPlaceholderText("⚠ Hãy dán link trước!")
            return
        data = self._combo_device.currentData()
        # data = ("pulse", "Virtual_Device.monitor") hoặc ("alsa", "sof-hda-dsp")
        # Encode thành chuỗi "pulse::<source_name>" hoặc "alsa::<device_name>"
        if data and data[0]:
            device_str = f"{data[0]}::{data[1]}"
        else:
            device_str = ""
        self.join_requested.emit(url, self._platform, device_str)

    def clear(self):
        self._inp.clear()