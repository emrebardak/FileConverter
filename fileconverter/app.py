"""Main window and entry point."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from fileconverter.convert_tab import ConvertTab
from fileconverter.summarize_tab import SummarizeTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileConverter")
        self.workdir = Path(tempfile.mkdtemp(prefix="fileconverter-"))
        self.convert_tab = ConvertTab(self.workdir)
        self.summarize_tab = SummarizeTab(self.convert_tab, self.workdir)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.convert_tab, "Convert")
        self.tabs.addTab(self.summarize_tab, "Summarize")
        self.setCentralWidget(self.tabs)
        self.statusBar()

    def closeEvent(self, event):
        # Hide first so closing feels instant, then let running conversions and
        # summaries finish (LibreOffice can take up to its 120 s timeout) before
        # deleting the session folder; otherwise they recreate files in it.
        self.hide()
        QThreadPool.globalInstance().waitForDone()
        shutil.rmtree(self.workdir, ignore_errors=True)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    return app.exec()
