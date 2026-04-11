"""
client/run_cabin.py
Entry point cho Cabin UI — CPU-only pipeline: Gipformer → NLLB → Piper TTS.

Chạy:
    python -m client.run_cabin
    hoặc: python client/run_cabin.py
"""
import logging
import sys

from PyQt6.QtWidgets import QApplication

from client.cabin_ui.main_window import ParalineMainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("paraline.cabin")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Paraline Cabin")
    app.setOrganizationName("Paraline")

    logger.info("=" * 55)
    logger.info("  🛖  Paraline CABIN MODE  (CPU-only)")
    logger.info("   Pipeline: Gipformer → NLLB → Piper TTS")
    logger.info("   ASR  :  http://127.0.0.1:8005")
    logger.info("   NLLB :  http://127.0.0.1:8002")
    logger.info("   TTS  :  http://127.0.0.1:8003")
    logger.info("=" * 55)

    window = ParalineMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
