"""Live PDF preview. Loads the page list from memory, so no file on disk is ever locked."""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from fileconverter import pages
from fileconverter.pages import Page


class PdfPreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc = QPdfDocument(self)
        self._buffer: QBuffer | None = None
        self._restore_page = 0
        self.doc.statusChanged.connect(self._on_status)
        self.view = QPdfView()
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        zoom_out, zoom_in, fit = QPushButton("−"), QPushButton("+"), QPushButton("Fit width")
        zoom_out.clicked.connect(lambda: self._zoom(1 / 1.25))
        zoom_in.clicked.connect(lambda: self._zoom(1.25))
        fit.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Live preview"))
        bar.addStretch()
        for button in (zoom_out, zoom_in, fit):
            bar.addWidget(button)

        empty = QLabel("Add files to see preview")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(empty)  # index 0
        self.stack.addWidget(self.view)  # index 1

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.stack, 1)

    def show_pages(self, page_list: list[Page]) -> None:
        """Show page_list, staying on the page the user was looking at."""
        if not page_list:
            self.doc.close()
            self.stack.setCurrentIndex(0)
            return
        self._restore_page = self.view.pageNavigator().currentPage()
        # ponytail: assembles on the UI thread; move to a worker if huge documents stutter.
        buffer = QBuffer(self)
        buffer.setData(QByteArray(pages.to_bytes(page_list)))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.doc.load(buffer)  # closes the previous document first
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
        self._buffer = buffer
        self.stack.setCurrentIndex(1)

    def jump(self, index: int) -> None:
        """Scroll to page index (clamped to the last page)."""
        if self.doc.pageCount():
            self.view.pageNavigator().jump(min(index, self.doc.pageCount() - 1), QPointF())

    def _on_status(self, status) -> None:
        if status == QPdfDocument.Status.Ready:
            self.jump(self._restore_page)

    def _zoom(self, factor: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() * factor)
