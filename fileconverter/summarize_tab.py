"""Summarize tab: pick a document (or the current one), get an AI summary, copy or save it."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from fileconverter import pages, summarize
from fileconverter.convert_tab import ConvertTab
from fileconverter.workers import run_task


def summarize_file(src: Path, style: str, api_key: str, model: str) -> str:
    return summarize.summarize(summarize.extract_markdown(src), style, api_key, model)


class SummarizeTab(QWidget):
    def __init__(self, convert_tab: ConvertTab, workdir: Path):
        super().__init__()
        self.convert_tab, self.workdir = convert_tab, workdir
        self.source: Path | None = None

        self.file_radio = QRadioButton("File:")
        self.file_radio.setChecked(True)
        self.current_radio = QRadioButton("Current document from the Convert tab")
        self.file_label = QLabel("No file chosen")
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self._choose)
        file_row = QHBoxLayout()
        for w in (self.file_radio, self.file_label, choose):
            file_row.addWidget(w)
        file_row.addStretch()

        self.style_group = QButtonGroup(self)
        style_row = QHBoxLayout()
        for key, label in (("Short", "Short"), ("Detailed", "Detailed"), ("Bullets", "Bullet points")):
            radio = QRadioButton(label)
            radio.setProperty("style", key)
            self.style_group.addButton(radio)
            style_row.addWidget(radio)
            radio.setChecked(key == "Short")
        style_row.addStretch()

        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.addItems(summarize.MODELS)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        save_key = QPushButton("Save key")
        save_key.clicked.connect(self._save_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(save_key)
        link = QLabel(f'Get a free key at <a href="{summarize.KEY_URL}">build.nvidia.com</a>')
        link.setOpenExternalLinks(True)
        settings = QFormLayout()
        settings.addRow("Model", self.model_box)
        settings.addRow("NVIDIA API key", key_row)
        settings.addRow("", link)

        self.run_btn = QPushButton("Summarize")
        self.run_btn.clicked.connect(self.run)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        copy_btn, save_btn = QPushButton("Copy"), QPushButton("Save…")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.result.toPlainText()))
        save_btn.clicked.connect(self._save_result)
        out_row = QHBoxLayout()
        out_row.addStretch()
        out_row.addWidget(copy_btn)
        out_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(file_row)
        layout.addWidget(self.current_radio)
        layout.addWidget(QLabel("Summary style"))
        layout.addLayout(style_row)
        layout.addLayout(settings)
        layout.addWidget(self.run_btn)
        layout.addWidget(self.result, 1)
        layout.addLayout(out_row)
        self._refresh_key_hint()

    def _choose(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(summarize.SUMMARY_EXTS))
        name, _ = QFileDialog.getOpenFileName(self, "Choose document", "", f"Documents ({patterns})")
        if name:
            self.source = Path(name)
            self.file_label.setText(self.source.name)
            self.file_radio.setChecked(True)

    def _refresh_key_hint(self) -> None:
        saved = summarize.get_api_key() is not None
        self.key_edit.setPlaceholderText("Key saved - paste a new one to replace" if saved else "nvapi-…")

    def _save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            return
        try:
            summarize.set_api_key(key)
        except Exception as e:
            QMessageBox.critical(self, "Could not save key", str(e))
            return
        self.key_edit.clear()
        self._refresh_key_hint()

    def run(self) -> None:
        key = summarize.get_api_key()
        if not key:
            QMessageBox.information(self, "API key needed", "Paste your NVIDIA API key and click Save key.")
            return
        if self.current_radio.isChecked():
            page_list = self.convert_tab.current_pages()
            if not page_list:
                QMessageBox.information(self, "Nothing to summarize", "The Convert tab has no pages yet.")
                return
            src = self.workdir / "current.pdf"
            try:
                pages.save(page_list, src)
            except Exception as e:
                QMessageBox.critical(self, "Could not prepare document", str(e))
                return
        elif self.source is None:
            QMessageBox.information(self, "No file", "Choose a PDF, DOCX or PPTX file first.")
            return
        else:
            src = self.source
        style = self.style_group.checkedButton().property("style")
        model = self.model_box.currentText().strip() or summarize.DEFAULT_MODEL
        self.run_btn.setEnabled(False)
        self.result.setPlainText("Summarizing…")
        run_task(summarize_file, src, style, key, model, on_done=self._show, on_failed=self._fail)

    def _show(self, text: str) -> None:
        self.result.setPlainText(text)
        self.run_btn.setEnabled(True)

    def _fail(self, message: str) -> None:
        self.result.clear()
        self.run_btn.setEnabled(True)
        QMessageBox.warning(self, "Summary failed", message)

    def _save_result(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Save summary", "summary.md", "Markdown (*.md);;Text (*.txt)")
        if name:
            try:
                Path(name).write_text(self.result.toPlainText(), encoding="utf-8")
            except OSError as e:
                QMessageBox.critical(self, "Save failed", f"Could not save {Path(name).name}: {e}")
