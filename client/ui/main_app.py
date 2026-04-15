"""
client/ui/main_app.py
Paraline MSAgent — PyQt6 Side-Panel GUI  (Light Indigo theme)
"""
import sys
import os
from dotenv import load_dotenv

# Tìm file .env ở thư mục gốc (root)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, ".env")
load_dotenv(env_path, override=True)

from PyQt6.QtWidgets import QApplication  # noqa: E402
from client.ui.main_window import ParalineMainWindow  # type: ignore[import-not-found]  # noqa: E402

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Paraline MSAgent")
    window = ParalineMainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()