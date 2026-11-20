"""Convert tab: add files, edit pages in a thumbnail grid, live preview, save."""
from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from fileconverter import images, office, pages
from fileconverter.images import IMAGE_EXTS, PageSetup
from fileconverter.office import OFFICE_EXTS
from fileconverter.pages import Page
from fileconverter.preview import PdfPreview
from fileconverter.workers import run_task

THUMB_PX = 140
TAG_COLORS = ["#dbeafe", "#dcfce7", "#fef9c3", "#fce7f3", "#ede9fe", "#ffedd5"]


def pil_to_qimage(img) -> QImage:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    return QImage(data, rgb.width, rgb.height, 3 * rgb.width, QImage.Format.Format_RGB888).copy()


def render_thumbs(page_list: list[tuple[int, Page]]) -> list[tuple[int, QImage]]:
    return [(pid, pil_to_qimage(pages.thumbnail(page, THUMB_PX))) for pid, page in page_list]


class ConvertTab(QWidget):
    changed = Signal()  # grid content or order changed

    def __init__(self, workdir: Path):
        super().__init__()
        self.workdir = workdir
        self.setup = PageSetup()
        self._pages: dict[int, Page] = {}  # page id -> Page; ids live in item data
        self._ids = itertools.count()
        self._colors: dict[Path, str] = {}
        self._status_rows: dict[Path, QListWidgetItem] = {}
        self._setup_generation = 0
        self.setAcceptDrops(True)

        # left: add / grid / page setup / status / save
        add_btn = QPushButton("Add files…")
        add_btn.clicked.connect(self._choose_files)
        self.quick_btn = QPushButton("Quick convert…")
        self.quick_btn.setToolTip("Convert one file straight to a PDF and choose where to save it")
        self.quick_btn.clicked.connect(self._choose_quick)
        drop_hint = QLabel("Drop files here, or")

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.ListMode)  # ListMode reorders rows reliably
        self.grid.setFlow(QListView.Flow.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setIconSize(QSize(THUMB_PX, THUMB_PX))
        self.grid.setSpacing(8)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.grid.setDefaultDropAction(Qt.DropAction.MoveAction)
        model = self.grid.model()
        model.rowsMoved.connect(self._on_grid_changed)
        model.rowsInserted.connect(self._on_grid_changed)
        model.rowsRemoved.connect(self._on_grid_changed)
        delete = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.grid)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.delete_selected)

        self.size_box = QComboBox()
        self.size_box.addItems(["A4", "Letter", "Fit"])
        self.orient_box = QComboBox()
        self.orient_box.addItems(["Auto", "Portrait", "Landscape"])
        self.margin_box = QDoubleSpinBox()
        self.margin_box.setRange(0, 50)
        self.margin_box.setSuffix(" mm")
        self.margin_box.setValue(self.setup.margin_mm)
        self.margin_box.setKeyboardTracking(False)
        # re-convert 300 ms after the last page-setup change
        self._setup_timer = QTimer(self)
        self._setup_timer.setSingleShot(True)
        self._setup_timer.setInterval(300)
        self._setup_timer.timeout.connect(self._on_setup_changed)
        for w in (self.size_box, self.orient_box):
            w.currentTextChanged.connect(self._setup_timer.start)
        self.margin_box.valueChanged.connect(self._setup_timer.start)
        setup_form = QFormLayout()
        setup_form.addRow("Image page size", self.size_box)
        setup_form.addRow("Orientation", self.orient_box)
        setup_form.addRow("Margin", self.margin_box)

        self.status = QListWidget()
        self.status.setMaximumHeight(110)

        self.save_btn = QPushButton("Save PDF…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)

        top = QHBoxLayout()
        top.addWidget(drop_hint)
        top.addWidget(add_btn)
        top.addWidget(self.quick_btn)
        top.addStretch()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(top)
        left_layout.addWidget(self.grid, 1)
        left_layout.addWidget(QLabel("Drag pages to reorder · Delete key removes selected pages"))
        left_layout.addLayout(setup_form)
        left_layout.addWidget(self.status)
        left_layout.addWidget(self.save_btn)

        splitter = QSplitter()
        splitter.addWidget(left)
        self.preview = PdfPreview()
        splitter.addWidget(self.preview)
        splitter.setSizes([600, 600])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        # refresh the preview 500 ms after the last change
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self.changed.connect(self._preview_timer.start)
        self.grid.itemClicked.connect(lambda item: self.preview.jump(self.grid.row(item)))

    def refresh_preview(self) -> None:
        self.preview.show_pages(self.current_pages())

    # ---- adding files

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])

    def _choose_files(self):
        patterns = " ".join(f"*{e}" for e in sorted(OFFICE_EXTS | IMAGE_EXTS))
        names, _ = QFileDialog.getOpenFileNames(self, "Add files", "", f"Supported files ({patterns})")
        self.add_files([Path(n) for n in names])

    def _job(self, path: Path):
        """(fn, args) that converts path to a PDF, or None after recording why it can't."""
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            return images.to_pdf, (path, self.setup, self.workdir)
        if ext in OFFICE_EXTS and office.find_soffice() is not None:
            return office.to_pdf, (path, self.workdir)
        missing_lo = ext in OFFICE_EXTS
        self._set_status(path, "Failed: LibreOffice not installed" if missing_lo else "Skipped: unsupported file type")
        return None

    def add_files(self, paths: list[Path]) -> None:
        lo_warned = False
        for path in paths:
            job = self._job(path)
            if job is not None:
                self._convert(path, job[0], *job[1])
            elif path.suffix.lower() in OFFICE_EXTS and not lo_warned:
                self._warn_libreoffice()
                lo_warned = True

    # ---- quick convert: one file straight to a PDF; the grid is not touched

    def _choose_quick(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(OFFICE_EXTS | IMAGE_EXTS))
        name, _ = QFileDialog.getOpenFileName(self, "Quick convert", "", f"Supported files ({patterns})")
        if name:
            self.quick_convert(Path(name))

    def quick_convert(self, src: Path) -> None:
        """Convert src in the background, then ask where to save it (defaults to src's name as .pdf)."""
        job = self._job(src)
        if job is None:
            if src.suffix.lower() in OFFICE_EXTS:
                self._warn_libreoffice()
            return
        self.quick_btn.setEnabled(False)
        self._set_status(src, "Converting…")
        run_task(
            job[0],
            *job[1],
            on_done=lambda pdf: self._quick_save(src, pdf),
            on_failed=lambda msg: self._quick_failed(src, msg),
        )

    def _quick_failed(self, src: Path, message: str) -> None:
        self.quick_btn.setEnabled(True)
        self._set_status(src, f"Failed: {message}")
        QMessageBox.warning(self, "Conversion failed", f"Could not convert {src.name}:\n{message}")

    def _quick_save(self, src: Path, pdf: Path) -> None:
        self.quick_btn.setEnabled(True)
        out = self._ask_save_path(str(src.with_suffix(".pdf")))
        if out is None:
            self._set_status(src, "Cancelled")
            return
        try:
            pages.save(pages.pages_of(pdf, src), out)
        except Exception as e:
            self._set_status(src, f"Failed: {e}")
            QMessageBox.critical(self, "Save failed", f"Could not save {out.name}:\n{e}")
            return
        self._set_status(src, f"Saved to {out}")

    def _convert(self, origin: Path, fn, *args) -> None:
        self._set_status(origin, "Converting…")
        setup = self.setup  # the setup this conversion starts with
        run_task(
            fn,
            *args,
            on_done=lambda pdf: self._on_converted(origin, pdf, setup),
            on_failed=lambda msg: self._set_status(origin, f"Failed: {msg}"),
        )

    def _on_converted(self, origin: Path, pdf: Path, setup: PageSetup) -> None:
        if origin.suffix.lower() in IMAGE_EXTS and setup != self.setup:
            self._convert(origin, images.to_pdf, origin, self.setup, self.workdir)  # setup changed meanwhile
            return
        try:
            converted = pages.pages_of(pdf, origin)
        except Exception as e:
            self._set_status(origin, f"Failed: {e}")
            return
        color = self._colors.setdefault(origin, TAG_COLORS[len(self._colors) % len(TAG_COLORS)])
        new = []
        for page in converted:
            pid = next(self._ids)
            self._pages[pid] = page
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setBackground(QColor(color))
            item.setSizeHint(QSize(THUMB_PX + 20, THUMB_PX + 40))
            self.grid.addItem(item)
            new.append((pid, page))
        self._set_status(origin, f"Done ({len(new)} pages)")
        self._load_thumbs(new)
        self._on_grid_changed()

    def _load_thumbs(self, page_list: list[tuple[int, Page]]) -> None:
        run_task(render_thumbs, page_list, on_done=self._apply_thumbs, on_failed=lambda m: None)

    def _apply_thumbs(self, thumbs: list[tuple[int, QImage]]) -> None:
        icons = {pid: QIcon(QPixmap.fromImage(img)) for pid, img in thumbs}
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            icon = icons.get(item.data(Qt.ItemDataRole.UserRole))
            if icon is not None:
                item.setIcon(icon)

    def _set_status(self, origin: Path, text: str) -> None:
        item = self._status_rows.get(origin)
        if item is None:
            item = self._status_rows[origin] = QListWidgetItem()
            self.status.addItem(item)
        item.setText(f"{origin.name} — {text}")

    def _warn_libreoffice(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("LibreOffice needed")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "LibreOffice is required for Office files.<br>"
            f'Download it free from <a href="{office.LIBREOFFICE_URL}">libreoffice.org</a>.<br>'
            "Images still work without it."
        )
        box.open()

    # ---- grid state

    def current_pages(self) -> list[Page]:
        ids = (self.grid.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.grid.count()))
        return [self._pages[pid] for pid in ids if pid is not None]

    def delete_selected(self) -> None:
        for item in self.grid.selectedItems():
            self.grid.takeItem(self.grid.row(item))

    def _on_grid_changed(self, *_) -> None:
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid is not None:  # None only mid-drop, before Qt copies item data
                item.setText(f"{row + 1} · {self._pages[pid].origin.name}")
        self.save_btn.setEnabled(self.grid.count() > 0)
        self.changed.emit()

    def _on_setup_changed(self, *_) -> None:
        """Re-convert image files with the new page setup; Office pages are untouched."""
        self.setup = PageSetup(self.size_box.currentText(), self.orient_box.currentText(), self.margin_box.value())
        self._setup_generation += 1
        generation = self._setup_generation
        origins = {p.origin for p in self.current_pages() if p.origin.suffix.lower() in IMAGE_EXTS}
        for origin in origins:
            run_task(
                images.to_pdf,
                origin,
                self.setup,
                self.workdir,
                on_done=lambda pdf, o=origin: self._on_reconverted(o, pdf, generation),
                on_failed=lambda msg, o=origin: self._set_status(o, f"Failed: {msg}"),
            )

    def _on_reconverted(self, origin: Path, pdf: Path, generation: int) -> None:
        if generation != self._setup_generation:
            return  # a newer setup change superseded this result
        changed = []
        for row in range(self.grid.count()):
            pid = self.grid.item(row).data(Qt.ItemDataRole.UserRole)
            page = self._pages[pid]
            if page.origin == origin:
                self._pages[pid] = Page(pdf, page.index, origin)
                changed.append((pid, self._pages[pid]))
        self._load_thumbs(changed)
        self._on_grid_changed()

    # ---- save

    def _ask_save_path(self, suggested: str) -> Path | None:
        """Save As dialog for a PDF; None if cancelled. Forces .pdf and confirms overwriting."""
        name, _ = QFileDialog.getSaveFileName(self, "Save PDF", suggested, "PDF (*.pdf)")
        if not name:
            return None
        out = Path(name)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")  # the dialog only confirmed overwriting the typed name
            if out.exists() and QMessageBox.question(
                self, "Overwrite?", f"{out.name} already exists. Replace it?"
            ) != QMessageBox.StandardButton.Yes:
                return None
        return out

    def _save(self) -> None:
        out = self._ask_save_path("output.pdf")
        if out is None:
            return
        try:
            pages.save(self.current_pages(), out)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not save {out.name}:\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved to {out}", 8000)
