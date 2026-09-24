"""
client/ui/main_app.py
Real-Time Meeting AI — PyQt6 Side-Panel GUI (Light Indigo theme)
"""
import sys
import os
import signal
from dotenv import load_dotenv

import logging

# Tắt cảnh báo Windows display driver ảo (DISPLAY5 / 0xe0000225)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.screen=false")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# Cấu hình logging console rõ ràng
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Tìm file .env ở thư mục gốc (root)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, ".env")
load_dotenv(env_path, override=True)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Pre-import torch before PyQt6 on Windows to prevent DLL collision [WinError 1114] with c10.dll
try:
    import torch
except Exception:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from client.ui.main_window import MeetingMainWindow
from client.ui.components.helpers import create_app_icon

def main():
    # Cho phép thoát sạch sẽ bằng Ctrl+C trên console mà không quăng traceback
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("Meeting AI Assistant")
    app.setWindowIcon(create_app_icon())

    window = MeetingMainWindow()
    window.show()

    # Timer nhỏ (500ms) để Python runtime có cơ hội bắt tín hiệu Ctrl+C từ terminal
    sig_timer = QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(500)

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        sys.exit(0)

if __name__ == "__main__":
    main()