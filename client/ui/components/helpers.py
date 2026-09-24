from PyQt6.QtWidgets import QWidget, QLabel, QScrollArea
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont


def card(obj_name: str) -> QWidget:
    w = QWidget()
    w.setObjectName(obj_name)
    return w


def label(text: str, obj_name: str) -> QLabel:
    l = QLabel(text)
    l.setObjectName(obj_name)
    return l


def scroll_wrap(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    return sa


def create_app_icon(size: int = 64) -> QIcon:
    """Tạo một icon ứng dụng sắc nét mang màu sắc emerald/dark theme."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Nền tròn xanh ngọc #00e5a0
    p.setBrush(QColor("#00e5a0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, size - 4, size - 4)

    # Vòng viền điểm xuyết
    pen = p.pen()
    pen.setColor(QColor("#00c88c"))
    pen.setWidth(2)
    p.setPen(pen)
    p.drawEllipse(2, 2, size - 4, size - 4)

    # Chữ 'M' ở giữa màu đen đậm
    p.setPen(QColor("#111111"))
    font = QFont("Segoe UI", int(size * 0.46), QFont.Weight.Black)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "M")
    p.end()
    return QIcon(pix)