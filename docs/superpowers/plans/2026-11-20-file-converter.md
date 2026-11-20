# FileConverter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop app that converts Office documents and images to PDF, lets the user edit pages (merge, reorder, delete, page setup) with a live preview, and summarizes PDF/DOCX/PPTX files through NVIDIA's free API, shipped as one `.exe`.

**Architecture:** Four Qt-free core modules (`images`, `pages`, `office`, `summarize`) hold all logic as plain functions and are unit-tested without a GUI. Five small PySide6 modules (`workers`, `preview`, `convert_tab`, `summarize_tab`, `app`) wire them into a two-tab window. Every slow call runs on `QThreadPool` and reports back through signals. PyInstaller packs everything into a single windowed `.exe`.

**Tech Stack:** Python 3.12, PySide6 6.12 (QtPdf), Pillow, pypdf, pypdfium2, MarkItDown, keyring, LibreOffice (headless, installed separately), NVIDIA API (OpenAI-compatible, stdlib `urllib`), pytest, PyInstaller.

**Spec:** [`docs/superpowers/specs/2026-11-20-file-converter-design.md`](../specs/2026-11-20-file-converter-design.md)

## Global Constraints

- Windows 10/11 only. Python `>=3.12`.
- Dependencies are exactly the pins in `requirements.txt` / `requirements-dev.txt` (Task 1). Do not add any other runtime dependency.
- License: MIT. Every runtime dependency must stay permissive or LGPL. **Never use PyMuPDF (AGPL).**
- `images.py`, `pages.py`, `office.py`, `summarize.py` must never import Qt.
- Conversion is **into PDF only**. Page setup applies to images only; Office pages keep their own layout.
- LibreOffice and API keys are **never** bundled in the `.exe`.
- API key lookup: `NVIDIA_API_KEY` env var first, then `keyring` service `"FileConverter"`, user `"nvidia"`. Never write the key to disk in plain text, never log it.
- API endpoint: `POST https://integrate.api.nvidia.com/v1/chat/completions`. Default model `nvidia/nemotron-3-ultra-550b-a55b`; fast alternative `nvidia/nemotron-3.5-lightning-30b-a3b`.
- Tests never touch the network or a real key. GUI tests run headless (`QT_QPA_PLATFORM=offscreen`).
- User-facing error strings are exactly the ones in the code below; tests match on them.
- Commits: one per task, conventional commit prefix (`feat:`, `build:`, `docs:`), work on `main` unless the executor uses a worktree.

## File map

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `requirements*.txt` | metadata, pytest config, pinned deps | 1 |
| `fileconverter/__init__.py` | version | 1 |
| `tests/conftest.py` | fixture files generated on the fly (no binaries in git) | 1 |
| `fileconverter/images.py` | image → PDF with `PageSetup` | 2 |
| `fileconverter/pages.py` | `Page` model, thumbnails, assemble/save PDF | 3 |
| `fileconverter/office.py` | find LibreOffice, Office → PDF | 4 |
| `fileconverter/summarize.py` | extract text, chunk, call NVIDIA API, key storage | 5 |
| `fileconverter/workers.py` | `run_task()` on `QThreadPool` | 6 |
| `fileconverter/preview.py` | `PdfPreview` widget (QPdfView from memory) | 6 |
| `tests/qt_helpers.py` | `qapp` fixture, `settle()` | 6 |
| `fileconverter/convert_tab.py` | grid, drag/drop, page setup, status, save | 7 |
| `fileconverter/summarize_tab.py` | summary UI | 8 |
| `fileconverter/app.py`, `fileconverter/__main__.py` | main window, temp dir lifecycle, entry point | 9 |
| `build.ps1`, `README.md` | one-file build, user docs | 10 |

Run every command from the repo root with the venv active (`.venv\Scripts\Activate.ps1`).

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `fileconverter/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: pytest config (`pythonpath = [".", "tests"]`, so tests can `import fileconverter` and `import qt_helpers`); helpers `write_text_pdf(path, text) -> Path`, `write_sized_pdf(path, widths) -> Path`; fixtures `workdir`, `tall_png` (600×900 PNG), `wide_jpg` (900×600 JPG), `transparent_png`, `text_pdf` (text "Hello summarizer world"), `sample_docx`, `sample_pptx`.

- [ ] **Step 1: Create the venv and pinned requirements**

`requirements.txt`:

```text
PySide6==6.12.0
pypdf==7.1.1
pypdfium2==5.15.2
pillow==13.0.0
markitdown[pdf,docx,pptx]==0.1.9
keyring==25.7.0
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest==9.2.0
pyinstaller==6.22.3
python-docx==1.2.0
```

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Expected: ends with `Successfully installed ...`. If pip hangs with no output for minutes, stop it and rerun with `--timeout 60`.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "fileconverter"
version = "0.1.0"
description = "Convert Office documents and images to PDF, edit pages with live preview, and summarize documents with AI."
license = "MIT"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "tests"]
```

- [ ] **Step 3: Create `fileconverter/__init__.py`**

```python
"""FileConverter: Office/images to PDF, page editing with live preview, AI summaries."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Create `tests/conftest.py`**

Fixture files are generated per test in `tmp_path`, so the repo holds no binary fixtures. Contents of `tests/conftest.py`:

```python
"""Generates small fixture files on the fly, so no binaries live in the repo."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def write_text_pdf(path: Path, text: str) -> Path:
    """Write a one-page PDF with real (extractable) text. Pure Python."""
    stream = b"BT /F1 12 Tf 72 770 Td (" + text.encode("latin-1") + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def write_sized_pdf(path: Path, widths: list[int]) -> Path:
    """Multi-page PDF; page i is widths[i] points wide (a marker for order checks)."""
    images = [Image.new("RGB", (w, 100), "white") for w in widths]
    images[0].save(path, "PDF", resolution=72, save_all=True, append_images=images[1:])
    return path


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def tall_png(tmp_path: Path) -> Path:
    p = tmp_path / "tall.png"
    Image.new("RGB", (600, 900), "red").save(p)
    return p


@pytest.fixture
def wide_jpg(tmp_path: Path) -> Path:
    p = tmp_path / "wide.jpg"
    Image.new("RGB", (900, 600), "blue").save(p)
    return p


@pytest.fixture
def transparent_png(tmp_path: Path) -> Path:
    p = tmp_path / "alpha.png"
    Image.new("RGBA", (300, 300), (0, 0, 0, 0)).save(p)
    return p


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return write_text_pdf(tmp_path / "text.pdf", "Hello summarizer world")


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Quarterly report", 1)
    d.add_paragraph("Revenue grew in every region.")
    p = tmp_path / "sample.docx"
    d.save(p)
    return p


@pytest.fixture
def sample_pptx(tmp_path: Path) -> Path:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Roadmap"
    slide.placeholders[1].text = "Ship version one"
    p = tmp_path / "sample.pptx"
    prs.save(p)
    return p
```

- [ ] **Step 5: Verify**

Run: `python -c "import fileconverter; print(fileconverter.__version__)"`
Expected: `0.1.0`

Run: `python -m pytest`
Expected: `no tests ran` (exit code 5). Collection must not error.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml requirements.txt requirements-dev.txt fileconverter/__init__.py tests/conftest.py
git commit -m "build: add project scaffold, pinned dependencies and test fixtures"
```

---

### Task 2: Image to PDF (`images.py`)

**Files:**
- Create: `fileconverter/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Consumes: fixtures `tall_png`, `wide_jpg`, `transparent_png`, `workdir` (Task 1).
- Produces:
  - `IMAGE_EXTS: set[str]`
  - `class ImageError(Exception)`
  - `@dataclass(frozen=True) class PageSetup(size: Literal["A4","Letter","Fit"]="A4", orientation: Literal["Auto","Portrait","Landscape"]="Auto", margin_mm: float=10.0)`
  - `to_pdf(src: Path, setup: PageSetup, workdir: Path) -> Path` — writes a new uniquely named PDF in `workdir` and returns its path.

Behaviour: 300 DPI. A4 210×297 mm, Letter 215.9×279.4 mm. `Fit` = image size + margins, orientation ignored. `Auto` = landscape when the image is wider than tall. Image scaled to fit inside margins, aspect kept, centered on white. Transparency flattened onto white, GIF first frame, EXIF rotation applied.

- [ ] **Step 1: Write the failing tests**

`tests/test_images.py`:

```python
from pathlib import Path

import pypdf
import pytest

from fileconverter.images import ImageError, PageSetup, to_pdf


def page_size(pdf: Path) -> tuple[float, float]:
    box = pypdf.PdfReader(pdf).pages[0].mediabox
    return float(box.width), float(box.height)


def test_a4_portrait(tall_png, workdir):
    w, h = page_size(to_pdf(tall_png, PageSetup("A4", "Portrait", 10), workdir))
    assert w == pytest.approx(595, abs=1)
    assert h == pytest.approx(842, abs=1)


def test_letter_portrait(tall_png, workdir):
    w, h = page_size(to_pdf(tall_png, PageSetup("Letter", "Portrait", 10), workdir))
    assert w == pytest.approx(612, abs=1)
    assert h == pytest.approx(792, abs=1)


def test_landscape_swaps(tall_png, workdir):
    w, h = page_size(to_pdf(tall_png, PageSetup("A4", "Landscape", 10), workdir))
    assert w == pytest.approx(842, abs=1)
    assert h == pytest.approx(595, abs=1)


def test_auto_picks_landscape_for_wide_image(wide_jpg, workdir):
    w, h = page_size(to_pdf(wide_jpg, PageSetup("A4", "Auto", 10), workdir))
    assert w > h


def test_fit_is_image_plus_margins(wide_jpg, workdir):
    # 900x600 px at 300 dpi + 2 * 10 mm margins
    w, h = page_size(to_pdf(wide_jpg, PageSetup("Fit", "Auto", 10), workdir))
    margin_pt = 10 / 25.4 * 72
    assert w == pytest.approx(900 / 300 * 72 + 2 * margin_pt, abs=1)
    assert h == pytest.approx(600 / 300 * 72 + 2 * margin_pt, abs=1)


def test_transparent_png_converts(transparent_png, workdir):
    out = to_pdf(transparent_png, PageSetup(), workdir)
    assert len(pypdf.PdfReader(out).pages) == 1


def test_two_conversions_never_collide(tall_png, workdir):
    a = to_pdf(tall_png, PageSetup(), workdir)
    b = to_pdf(tall_png, PageSetup(), workdir)
    assert a != b


def test_corrupt_image_raises(tmp_path, workdir):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(ImageError):
        to_pdf(bad, PageSetup(), workdir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_images.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'fileconverter.images'`

- [ ] **Step 3: Implement `fileconverter/images.py`**

```python
"""Image -> PDF with page setup. No Qt imports."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
DPI = 300
PAPER_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}


class ImageError(Exception):
    """The file could not be read as an image."""


@dataclass(frozen=True)
class PageSetup:
    size: Literal["A4", "Letter", "Fit"] = "A4"
    orientation: Literal["Auto", "Portrait", "Landscape"] = "Auto"
    margin_mm: float = 10.0


def _mm_to_px(mm: float) -> int:
    return round(mm / 25.4 * DPI)


def _flatten(im: Image.Image) -> Image.Image:
    """Return an RGB image; transparent areas become white."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return im.convert("RGB")


def to_pdf(src: Path, setup: PageSetup, workdir: Path) -> Path:
    try:
        with Image.open(src) as raw:
            raw.seek(0)  # GIF/TIFF: first frame only
            im = _flatten(ImageOps.exif_transpose(raw))
    except (OSError, SyntaxError, ValueError) as e:
        raise ImageError(f"cannot read image: {src.name}") from e

    margin = _mm_to_px(setup.margin_mm)
    if setup.size == "Fit":
        page_w, page_h = im.width + 2 * margin, im.height + 2 * margin
    else:
        w_mm, h_mm = PAPER_MM[setup.size]
        landscape = setup.orientation == "Landscape" or (
            setup.orientation == "Auto" and im.width > im.height
        )
        if landscape:
            w_mm, h_mm = h_mm, w_mm
        page_w, page_h = _mm_to_px(w_mm), _mm_to_px(h_mm)
        box_w, box_h = max(page_w - 2 * margin, 1), max(page_h - 2 * margin, 1)
        scale = min(box_w / im.width, box_h / im.height)
        new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        if new_size != im.size:
            im = im.resize(new_size, Image.Resampling.LANCZOS)

    page = Image.new("RGB", (page_w, page_h), "white")
    page.paste(im, ((page_w - im.width) // 2, (page_h - im.height) // 2))
    out = workdir / f"{src.stem}-{uuid.uuid4().hex[:8]}.pdf"
    page.save(out, "PDF", resolution=DPI)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_images.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```powershell
git add fileconverter/images.py tests/test_images.py
git commit -m "feat: convert images to PDF with page size, orientation and margins"
```

---

### Task 3: Page model, thumbnails, assemble and save (`pages.py`)

**Files:**
- Create: `fileconverter/pages.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `write_sized_pdf` helper, `workdir` fixture (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Page(source_pdf: Path, index: int, origin: Path)` — hashable.
  - `pages_of(pdf: Path, origin: Path) -> list[Page]`
  - `thumbnail(page: Page, max_px: int = 160) -> PIL.Image.Image` — thread-safe (global pdfium lock).
  - `to_bytes(pages: list[Page]) -> bytes` — raises `ValueError` on an empty list.
  - `save(pages: list[Page], out: Path) -> None` — atomic: temp file + `os.replace`, temp removed on failure.

- [ ] **Step 1: Write the failing tests**

`tests/test_pages.py`:

```python
import io

import pypdf
import pytest

from conftest import write_sized_pdf
from fileconverter.pages import Page, pages_of, save, thumbnail, to_bytes


def widths(data: bytes) -> list[int]:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return [round(float(p.mediabox.width)) for p in reader.pages]


@pytest.fixture
def two_sources(tmp_path):
    a = write_sized_pdf(tmp_path / "a.pdf", [100, 200, 300])
    b = write_sized_pdf(tmp_path / "b.pdf", [400])
    return pages_of(a, tmp_path / "a.pptx"), pages_of(b, tmp_path / "b.jpg")


def test_pages_of_counts_pages(two_sources):
    a, b = two_sources
    assert [p.index for p in a] == [0, 1, 2]
    assert len(b) == 1
    assert a[0].origin.name == "a.pptx"


def test_to_bytes_merges_reorders_and_deletes(two_sources):
    a, b = two_sources
    order = [b[0], a[2], a[0]]  # page a[1] deleted
    assert widths(to_bytes(order)) == [400, 300, 100]


def test_to_bytes_empty_raises():
    with pytest.raises(ValueError):
        to_bytes([])


def test_save_writes_file_and_leaves_no_temp(two_sources, tmp_path):
    a, _ = two_sources
    out = tmp_path / "out.pdf"
    save(a, out)
    assert widths(out.read_bytes()) == [100, 200, 300]
    assert not (tmp_path / "out.pdf.tmp").exists()


def test_save_overwrites_existing(two_sources, tmp_path):
    a, b = two_sources
    out = tmp_path / "out.pdf"
    save(a, out)
    save(b, out)
    assert widths(out.read_bytes()) == [400]


def test_thumbnail_fits_max_px(two_sources):
    a, _ = two_sources
    img = thumbnail(a[2], max_px=64)
    assert max(img.size) <= 64


def test_page_is_hashable():
    p = Page(source_pdf=__file__, index=0, origin=__file__)
    assert {p: 1}[p] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pages.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'fileconverter.pages'`

- [ ] **Step 3: Implement `fileconverter/pages.py`**

```python
"""Page model: thumbnails, assemble PDF bytes, save. No Qt imports."""
from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdf
import pypdfium2 as pdfium
from PIL import Image

# pdfium is not thread-safe; thumbnails render in worker threads.
_PDFIUM_LOCK = threading.Lock()


@dataclass(frozen=True)
class Page:
    source_pdf: Path  # intermediate PDF in the session temp dir
    index: int  # 0-based page index in source_pdf
    origin: Path  # original file the user added


def pages_of(pdf: Path, origin: Path) -> list[Page]:
    count = len(pypdf.PdfReader(pdf).pages)
    return [Page(pdf, i, origin) for i in range(count)]


def thumbnail(page: Page, max_px: int = 160) -> Image.Image:
    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(page.source_pdf))
        try:
            pg = doc[page.index]
            w, h = pg.get_size()
            img = pg.render(scale=max_px / max(w, h)).to_pil()
            pg.close()
        finally:
            doc.close()
    img.thumbnail((max_px, max_px))  # guard against rounding past max_px
    return img


def to_bytes(pages: list[Page]) -> bytes:
    if not pages:
        raise ValueError("no pages to write")
    readers: dict[Path, pypdf.PdfReader] = {}
    writer = pypdf.PdfWriter()
    for page in pages:
        if page.source_pdf not in readers:
            readers[page.source_pdf] = pypdf.PdfReader(page.source_pdf)
        writer.add_page(readers[page.source_pdf].pages[page.index])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def save(pages: list[Page], out: Path) -> None:
    data = to_bytes(pages)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pages.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```powershell
git add fileconverter/pages.py tests/test_pages.py
git commit -m "feat: add page model with thumbnails, in-memory assembly and atomic save"
```

---

### Task 4: Office to PDF through LibreOffice (`office.py`)

**Files:**
- Create: `fileconverter/office.py`
- Test: `tests/test_office.py`

**Interfaces:**
- Consumes: fixtures `sample_docx`, `sample_pptx`, `workdir` (Task 1).
- Produces:
  - `OFFICE_EXTS: set[str]`, `LIBREOFFICE_URL: str`
  - `class LibreOfficeMissing(Exception)`, `class ConversionError(Exception)`
  - `find_soffice() -> Path | None` — PATH, then both Program Files folders, then registry `HKLM\SOFTWARE\LibreOffice\UNO\InstallPath`.
  - `to_pdf(src: Path, workdir: Path, timeout: int = 120) -> Path` — unique profile dir and out dir per run.

- [ ] **Step 1: Install LibreOffice**

The conversion tests skip without it, and **a skipped test is not a passed test**. Install LibreOffice 7.6+ from https://www.libreoffice.org/download/ (default install path), then open a new terminal and reactivate the venv.

Run: `Test-Path "C:\Program Files\LibreOffice\program\soffice.exe"`
Expected: `True`

- [ ] **Step 2: Write the failing tests**

`tests/test_office.py`:

```python
import pypdf
import pytest

from fileconverter import office

needs_lo = pytest.mark.skipif(office.find_soffice() is None, reason="LibreOffice not installed")


def test_find_soffice_does_not_raise():
    result = office.find_soffice()
    assert result is None or result.exists()


def test_missing_libreoffice_raises(monkeypatch, sample_docx, workdir):
    monkeypatch.setattr(office, "find_soffice", lambda: None)
    with pytest.raises(office.LibreOfficeMissing):
        office.to_pdf(sample_docx, workdir)


@needs_lo
def test_docx_to_pdf(sample_docx, workdir):
    out = office.to_pdf(sample_docx, workdir)
    assert len(pypdf.PdfReader(out).pages) >= 1


@needs_lo
def test_pptx_to_pdf(sample_pptx, workdir):
    out = office.to_pdf(sample_pptx, workdir)
    assert len(pypdf.PdfReader(out).pages) >= 1


@needs_lo
def test_same_stem_does_not_collide(sample_docx, sample_pptx, workdir):
    # sample.docx and sample.pptx both become sample.pdf
    a = office.to_pdf(sample_docx, workdir)
    b = office.to_pdf(sample_pptx, workdir)
    assert a != b and a.exists() and b.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_office.py -v`
Expected: collection error `ImportError: cannot import name 'office' from 'fileconverter'`

- [ ] **Step 4: Implement `fileconverter/office.py`**

```python
"""Office file -> PDF through headless LibreOffice. No Qt imports."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

OFFICE_EXTS = {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".odp", ".ods", ".rtf"}
LIBREOFFICE_URL = "https://www.libreoffice.org/download/"

_CANDIDATES = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]


class LibreOfficeMissing(Exception):
    """soffice.exe could not be found."""


class ConversionError(Exception):
    """LibreOffice failed or timed out."""


def _from_registry() -> Path | None:
    try:
        import winreg
    except ImportError:  # not Windows
        return None
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\LibreOffice\UNO\InstallPath",
                0,
                winreg.KEY_READ | view,
            ) as key:
                exe = Path(winreg.QueryValueEx(key, "")[0]) / "soffice.exe"
                if exe.exists():
                    return exe
        except OSError:
            continue
    return None


def find_soffice() -> Path | None:
    on_path = shutil.which("soffice")
    if on_path:
        return Path(on_path)
    for candidate in _CANDIDATES:
        if candidate.exists():
            return candidate
    return _from_registry()


def to_pdf(src: Path, workdir: Path, timeout: int = 120) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise LibreOfficeMissing("LibreOffice is required for Office files")
    run_dir = Path(tempfile.mkdtemp(prefix="lo-", dir=workdir)).resolve()
    profile, outdir = run_dir / "profile", run_dir / "out"
    cmd = [
        str(soffice),
        "--headless",
        "--norestore",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(src),
    ]
    try:
        # ponytail: kills soffice.exe on timeout; a stray soffice.bin child may linger.
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError(f"{src.name}: timed out after {timeout}s") from e
    out = outdir / f"{src.stem}.pdf"
    if result.returncode != 0 or not out.exists():
        detail = (result.stderr or result.stdout).strip() or "LibreOffice produced no PDF"
        raise ConversionError(f"{src.name}: {detail}")
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_office.py -v -rs`
Expected: `5 passed`. If you see `2 passed, 3 skipped` with reason `LibreOffice not installed`, Step 1 is not done; this task is **not** complete until all 5 pass.

- [ ] **Step 6: Commit**

```powershell
git add fileconverter/office.py tests/test_office.py
git commit -m "feat: convert Office documents to PDF with headless LibreOffice"
```

---

### Task 5: Text extraction and NVIDIA summaries (`summarize.py`)

**Files:**
- Create: `fileconverter/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: fixtures `text_pdf`, `sample_docx`, `sample_pptx` (Task 1).
- Produces:
  - `SUMMARY_EXTS`, `API_URL`, `KEY_URL`, `MODELS: list[str]`, `DEFAULT_MODEL = MODELS[0]`, `PROMPTS: dict[Style, str]`, `Style = Literal["Short","Detailed","Bullets"]`
  - Exceptions, all subclasses of `SummarizeError` with user-facing messages: `NoTextFound`, `BadApiKey`, `RateLimited`, `Offline`, `ApiError(status, body)`.
  - `extract_markdown(src: Path) -> str`
  - `chunk(text: str, max_chars: int = 100_000) -> list[str]`
  - `summarize(text: str, style: Style, api_key: str, model: str = DEFAULT_MODEL) -> str` — one call for one chunk; N chunk calls + 1 combine call otherwise. Strips `<think>…</think>`. Empty reply raises `SummarizeError`.
  - `get_api_key() -> str | None`, `set_api_key(key: str) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_summarize.py` (stubs `urllib.request.urlopen` and `keyring`; no network):

```python
import io
import json
import urllib.error
import urllib.request

import pytest

from fileconverter import summarize as s


# ---------- extract + chunk ----------

def test_extract_markdown_pdf(text_pdf):
    assert "Hello summarizer world" in s.extract_markdown(text_pdf)


def test_extract_markdown_docx(sample_docx):
    assert "Revenue grew" in s.extract_markdown(sample_docx)


def test_extract_markdown_pptx(sample_pptx):
    assert "Roadmap" in s.extract_markdown(sample_pptx)


def test_extract_markdown_empty_raises(tmp_path, monkeypatch):
    class Empty:
        text_content = "   \n"

    class FakeMarkItDown:
        def convert(self, _):
            return Empty()

    import markitdown

    monkeypatch.setattr(markitdown, "MarkItDown", FakeMarkItDown)
    with pytest.raises(s.NoTextFound):
        s.extract_markdown(tmp_path / "x.pdf")


def test_chunk_small_text_is_one_chunk():
    assert s.chunk("a\n\nb", max_chars=100) == ["a\n\nb"]


def test_chunk_respects_limit_and_paragraphs():
    text = "\n\n".join(["x" * 40] * 5)
    parts = s.chunk(text, max_chars=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n\n".join(parts) == text


def test_chunk_hard_splits_huge_paragraph():
    parts = s.chunk("y" * 250, max_chars=100)
    assert [len(p) for p in parts] == [100, 100, 50]


# ---------- API ----------

def ok_response(content: str):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def http_error(code: int):
    return urllib.error.HTTPError(s.API_URL, code, "err", {}, io.BytesIO(b"details"))


@pytest.fixture
def calls(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return ok_response(f"summary {len(sent)}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


def test_single_chunk_one_call(calls):
    assert s.summarize("short text", "Short", "key", "m") == "summary 1"
    assert len(calls) == 1
    assert calls[0]["model"] == "m"
    assert calls[0]["messages"][0]["content"] == s.PROMPTS["Short"]


def test_many_chunks_map_reduce(calls, monkeypatch):
    monkeypatch.setattr(s, "chunk", lambda text: ["c1", "c2", "c3"])
    assert s.summarize("long", "Bullets", "key", "m") == "summary 4"
    assert len(calls) == 4  # 3 chunks + 1 combine
    assert calls[-1]["messages"][0]["content"] == s.PROMPTS["Bullets"]


def test_think_block_is_stripped(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: ok_response("<think>hmm</think>\nFinal"))
    assert s.summarize("text", "Short", "key", "m") == "Final"


def test_empty_reply_raises(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: ok_response(None))
    with pytest.raises(s.SummarizeError, match="empty reply"):
        s.summarize("text", "Short", "key", "m")


@pytest.mark.parametrize(
    "error, expected",
    [
        (http_error(401), s.BadApiKey),
        (http_error(403), s.BadApiKey),
        (http_error(429), s.RateLimited),
        (http_error(500), s.ApiError),
        (urllib.error.URLError("no route"), s.Offline),
        (TimeoutError(), s.Offline),
    ],
)
def test_errors_map_to_types(monkeypatch, error, expected):
    def boom(request, timeout):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(expected):
        s.summarize("text", "Short", "key", "m")


# ---------- API key ----------

def test_env_key_wins(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env")
    assert s.get_api_key() == "nvapi-env"


def test_keyring_key(monkeypatch):
    import keyring

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = {}
    monkeypatch.setattr(keyring, "set_password", lambda svc, user, pw: store.__setitem__((svc, user), pw))
    monkeypatch.setattr(keyring, "get_password", lambda svc, user: store.get((svc, user)))
    s.set_api_key("  nvapi-stored  ")
    assert s.get_api_key() == "nvapi-stored"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_summarize.py -v`
Expected: collection error `ImportError: cannot import name 'summarize' from 'fileconverter'`

- [ ] **Step 3: Implement `fileconverter/summarize.py`**

```python
"""File -> Markdown -> NVIDIA API -> summary. No Qt imports."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

SUMMARY_EXTS = {".pdf", ".docx", ".pptx"}
Style = Literal["Short", "Detailed", "Bullets"]

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
KEY_URL = "https://build.nvidia.com"
MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b"]
DEFAULT_MODEL = MODELS[0]
KEYRING_SERVICE, KEYRING_USER = "FileConverter", "nvidia"

_COMMON = " Use only information from the document. Reply in the document's language."
PROMPTS: dict[str, str] = {
    "Short": "Summarize the document in one paragraph of at most 5 sentences." + _COMMON,
    "Detailed": "Summarize the document in several paragraphs covering every main section." + _COMMON,
    "Bullets": "Summarize the document as 5-10 concise bullet points." + _COMMON,
}
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class SummarizeError(Exception):
    """Base class; str(error) is a user-facing message."""


class NoTextFound(SummarizeError):
    pass


class BadApiKey(SummarizeError):
    pass


class RateLimited(SummarizeError):
    pass


class Offline(SummarizeError):
    pass


class ApiError(SummarizeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"NVIDIA API error {status}: {body[:200]}")
        self.status, self.body = status, body


def extract_markdown(src: Path) -> str:
    from markitdown import MarkItDown  # heavy import (onnxruntime); load on first use

    text = MarkItDown().convert(str(src)).text_content or ""
    if not text.strip():
        raise NoTextFound("No text found - scanned PDF? OCR is not supported.")
    return text


def chunk(text: str, max_chars: int = 100_000) -> list[str]:
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > max_chars:  # hard-split an oversized paragraph
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


def _chat(system: str, user: str, api_key: str, model: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 2048,
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:  # must come before URLError (subclass)
        detail = e.read().decode("utf-8", "replace")
        if e.code in (401, 403):
            raise BadApiKey("API key rejected - check it on build.nvidia.com.") from e
        if e.code == 429:
            raise RateLimited("Rate limited - wait a minute and try again.") from e
        raise ApiError(e.code, detail) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise Offline("Cannot reach NVIDIA API - check your internet connection.") from e
    content = _THINK.sub("", data["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise SummarizeError("The model returned an empty reply - try again or pick another model.")
    return content


def summarize(text: str, style: Style, api_key: str, model: str = DEFAULT_MODEL) -> str:
    parts = chunk(text)
    if not parts:
        raise NoTextFound("No text found - scanned PDF? OCR is not supported.")
    if len(parts) == 1:
        return _chat(PROMPTS[style], parts[0], api_key, model)
    partials = [_chat(PROMPTS["Detailed"], part, api_key, model) for part in parts]
    return _chat(PROMPTS[style], "\n\n".join(partials), api_key, model)


def get_api_key() -> str | None:
    env = os.environ.get("NVIDIA_API_KEY", "").strip()
    if env:
        return env
    import keyring
    from keyring.errors import KeyringError

    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except KeyringError:
        return None


def set_api_key(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_summarize.py -v`
Expected: `19 passed`

- [ ] **Step 5 (optional): One live call**

Only if you have a key in `NVIDIA_API_KEY`. Sends one short sentence to NVIDIA.

```powershell
python -c "from fileconverter import summarize as s; print(s.summarize('The library opens at 9am and closes at 5pm.', 'Short', s.get_api_key()))"
```

Expected: a one-sentence summary within about 10 s.

- [ ] **Step 6: Commit**

```powershell
git add fileconverter/summarize.py tests/test_summarize.py
git commit -m "feat: summarize documents with MarkItDown and the NVIDIA API"
```

---

### Task 6: Background workers and live PDF preview (`workers.py`, `preview.py`)

**Files:**
- Create: `fileconverter/workers.py`
- Create: `fileconverter/preview.py`
- Create: `tests/qt_helpers.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `images.to_pdf`, `PageSetup` (Task 2); `pages.pages_of`, `pages.to_bytes`, `Page` (Task 3).
- Produces:
  - `workers.run_task(fn, *args, on_done: Callable[[object], None], on_failed: Callable[[str], None]) -> None` — runs `fn(*args)` on `QThreadPool.globalInstance()`; callbacks run on the UI thread; any exception becomes `on_failed(str(e))`.
  - `preview.PdfPreview(QWidget)` with attributes `doc: QPdfDocument`, `view: QPdfView`, `stack: QStackedWidget` (index 0 = "Add files to see preview", index 1 = viewer) and methods `show_pages(page_list: list[Page]) -> None`, `jump(index: int) -> None` (clamped to the last page).
  - `tests/qt_helpers.py`: session fixture `qapp` (on teardown it deletes every top-level widget while the app still exists; without that the test process crashes on exit about 1 run in 8), function `settle(qapp, rounds=6)`. GUI test modules start with `from qt_helpers import qapp, settle` **before** any other Qt import, so the offscreen platform is set first.

The preview loads PDF bytes from a `QBuffer`, so no file on disk is ever locked by the viewer.

- [ ] **Step 1: Create `tests/qt_helpers.py`**

```python
"""Shared helpers for the headless GUI tests. Import before any other Qt import."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window, works in CI

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    # Delete every widget while the app still exists. Left to interpreter shutdown,
    # they are destroyed in random order and the process crashes on exit.
    QThreadPool.globalInstance().waitForDone(15000)
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)


def settle(qapp, rounds: int = 6) -> None:
    """Let worker threads finish and deliver their queued signals."""
    for _ in range(rounds):
        QThreadPool.globalInstance().waitForDone(15000)
        qapp.processEvents()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_preview.py`:

```python
from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest

from fileconverter import images, pages
from fileconverter.images import PageSetup
from fileconverter.preview import PdfPreview


@pytest.fixture
def three_pages(tall_png, wide_jpg, workdir):
    a = images.to_pdf(tall_png, PageSetup(), workdir)
    b = images.to_pdf(wide_jpg, PageSetup(), workdir)
    return pages.pages_of(a, tall_png) + pages.pages_of(b, wide_jpg) + pages.pages_of(a, tall_png)


def test_shows_pages(qapp, three_pages):
    preview = PdfPreview()
    preview.show_pages(three_pages)
    settle(qapp)
    assert preview.doc.pageCount() == 3
    assert preview.stack.currentIndex() == 1


def test_reload_with_fewer_pages(qapp, three_pages):
    preview = PdfPreview()
    preview.show_pages(three_pages)
    settle(qapp)
    preview.show_pages(three_pages[:1])
    settle(qapp)
    assert preview.doc.pageCount() == 1


def test_empty_list_shows_placeholder(qapp, three_pages):
    preview = PdfPreview()
    preview.show_pages(three_pages)
    settle(qapp)
    preview.show_pages([])
    assert preview.stack.currentIndex() == 0
    assert preview.doc.pageCount() == 0


def test_jump_clamps_to_last_page(qapp, three_pages):
    preview = PdfPreview()
    preview.show_pages(three_pages)
    settle(qapp)
    preview.jump(99)
    assert preview.view.pageNavigator().currentPage() == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_preview.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'fileconverter.preview'`

- [ ] **Step 4: Implement `fileconverter/workers.py`**

```python
"""Run blocking work on Qt's thread pool and get the result back on the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as e:  # report every failure to the UI thread
            self.signals.failed.emit(str(e) or type(e).__name__)
        else:
            self.signals.done.emit(result)


_live_tasks: set[_Task] = set()  # keeps signal objects alive until delivered


def run_task(fn, *args, on_done, on_failed) -> None:
    """Run fn(*args) on the global thread pool; callbacks run on the UI thread."""
    task = _Task(fn, args)
    _live_tasks.add(task)

    def finish(callback, value):
        _live_tasks.discard(task)
        callback(value)

    task.signals.done.connect(lambda v: finish(on_done, v))
    task.signals.failed.connect(lambda m: finish(on_failed, m))
    task.setAutoDelete(False)
    QThreadPool.globalInstance().start(task)
```

- [ ] **Step 5: Implement `fileconverter/preview.py`**

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_preview.py -v`
Expected: `4 passed`

- [ ] **Step 7: Commit**

```powershell
git add fileconverter/workers.py fileconverter/preview.py tests/qt_helpers.py tests/test_preview.py
git commit -m "feat: add background task runner and in-memory live PDF preview"
```

---

### Task 7: Convert tab (`convert_tab.py`)

**Files:**
- Create: `fileconverter/convert_tab.py`
- Test: `tests/test_convert_tab.py`

**Interfaces:**
- Consumes: `images` (Task 2), `pages` (Task 3), `office` (Task 4), `workers.run_task` and `preview.PdfPreview` (Task 6), `qt_helpers` (Task 6).
- Produces: `ConvertTab(QWidget)`, constructed as `ConvertTab(workdir: Path)`:
  - Signal `changed` (grid content or order changed).
  - Widgets: `grid: QListWidget`, `status: QListWidget`, `save_btn`, `size_box`, `orient_box`, `margin_box`, `preview: PdfPreview`.
  - Methods: `add_files(paths: list[Path])`, `current_pages() -> list[Page]` (grid order), `delete_selected()`, `refresh_preview()`.
  - Uses `self.window().statusBar()` after a save, so it expects to live inside a `QMainWindow` (Task 9).

Design notes for the implementer:
- The grid uses `ListMode` + `Flow.LeftToRight` + wrapping instead of `IconMode`: same look, but `InternalMove` reordering is reliable and emits `rowsMoved`.
- Each grid item stores an `int` page id in `Qt.ItemDataRole.UserRole`; `self._pages` maps id → `Page`. Ints survive Qt's drag/drop copy; Python objects may not.
- Page setup changes bump `_setup_generation`; results from an older generation are dropped, so fast clicking never applies a stale conversion.
- Office files are refused up front when `find_soffice()` is `None`, with one warning dialog per batch.

- [ ] **Step 1: Write the failing tests**

`tests/test_convert_tab.py`:

```python
from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest
from PySide6.QtCore import QModelIndex

from fileconverter.convert_tab import ConvertTab


@pytest.fixture
def tab(qapp, workdir):
    return ConvertTab(workdir)


def test_add_images_fills_grid_with_thumbnails(qapp, tab, tall_png, wide_jpg):
    tab.add_files([tall_png, wide_jpg])
    settle(qapp)
    assert tab.grid.count() == 2
    assert {p.origin.name for p in tab.current_pages()} == {"tall.png", "wide.jpg"}
    assert all(not tab.grid.item(r).icon().isNull() for r in range(2))
    assert tab.save_btn.isEnabled()


def test_delete_selected_removes_pages(qapp, tab, tall_png, wide_jpg):
    tab.add_files([tall_png, wide_jpg])
    settle(qapp)
    tab.grid.item(0).setSelected(True)
    tab.delete_selected()
    assert tab.grid.count() == 1
    assert tab.grid.item(0).text().startswith("1 · ")


def test_reorder_updates_order_and_labels(qapp, tab, tall_png, wide_jpg):
    tab.add_files([tall_png, wide_jpg])
    settle(qapp)
    first = tab.current_pages()[0].origin.name
    assert tab.grid.model().moveRow(QModelIndex(), 1, QModelIndex(), 0)
    assert tab.current_pages()[1].origin.name == first
    assert tab.grid.item(1).text() == f"2 · {first}"


def test_unsupported_file_is_skipped(qapp, tab, tmp_path):
    odd = tmp_path / "notes.xyz"
    odd.write_text("x")
    tab.add_files([odd])
    settle(qapp)
    assert tab.grid.count() == 0
    assert "Skipped" in tab.status.item(0).text()


def test_preview_follows_grid(qapp, tab, tall_png, wide_jpg):
    tab.add_files([tall_png, wide_jpg])
    settle(qapp)
    tab.refresh_preview()
    settle(qapp)
    assert tab.preview.doc.pageCount() == 2
    tab.grid.item(0).setSelected(True)
    tab.delete_selected()
    tab.refresh_preview()
    settle(qapp)
    assert tab.preview.doc.pageCount() == 1


def test_page_setup_change_reconverts_images(qapp, tab, tall_png):
    tab.add_files([tall_png])
    settle(qapp)
    before = tab.current_pages()[0].source_pdf
    tab.size_box.setCurrentText("Letter")
    settle(qapp)
    after = tab.current_pages()[0].source_pdf
    assert after != before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_convert_tab.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'fileconverter.convert_tab'`

- [ ] **Step 3: Implement `fileconverter/convert_tab.py`**

```python
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
        for w in (self.size_box, self.orient_box):
            w.currentTextChanged.connect(self._on_setup_changed)
        self.margin_box.valueChanged.connect(self._on_setup_changed)
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

    def add_files(self, paths: list[Path]) -> None:
        lo_warned = False
        for path in paths:
            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                self._convert(path, images.to_pdf, path, self.setup, self.workdir)
            elif ext in OFFICE_EXTS:
                if office.find_soffice() is None:
                    self._set_status(path, "Failed: LibreOffice not installed")
                    if not lo_warned:
                        self._warn_libreoffice()
                        lo_warned = True
                    continue
                self._convert(path, office.to_pdf, path, self.workdir)
            else:
                self._set_status(path, "Skipped: unsupported file type")

    def _convert(self, origin: Path, fn, *args) -> None:
        self._set_status(origin, "Converting…")
        run_task(
            fn,
            *args,
            on_done=lambda pdf: self._on_converted(origin, pdf),
            on_failed=lambda msg: self._set_status(origin, f"Failed: {msg}"),
        )

    def _on_converted(self, origin: Path, pdf: Path) -> None:
        color = self._colors.setdefault(origin, TAG_COLORS[len(self._colors) % len(TAG_COLORS)])
        new = []
        for page in pages.pages_of(pdf, origin):
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

    def _save(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Save PDF", "output.pdf", "PDF (*.pdf)")
        if not name:
            return
        out = Path(name)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
        try:
            pages.save(self.current_pages(), out)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not save {out.name}:\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved to {out}", 8000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_convert_tab.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```powershell
git add fileconverter/convert_tab.py tests/test_convert_tab.py
git commit -m "feat: add convert tab with page grid, page setup and live preview"
```

---

### Task 8: Summarize tab (`summarize_tab.py`)

**Files:**
- Create: `fileconverter/summarize_tab.py`
- Test: `tests/test_summarize_tab.py`

**Interfaces:**
- Consumes: `summarize` (Task 5), `pages.save` (Task 3), `ConvertTab.current_pages()` (Task 7), `workers.run_task` (Task 6).
- Produces:
  - `summarize_file(src: Path, style: str, api_key: str, model: str) -> str`
  - `SummarizeTab(QWidget)`, constructed as `SummarizeTab(convert_tab: ConvertTab, workdir: Path)`, with attributes `convert_tab`, `source: Path | None`, `file_radio`, `current_radio`, `style_group` (buttons carry a `"style"` property: `"Short"`, `"Detailed"`, `"Bullets"`), `model_box`, `key_edit`, `run_btn`, `result`; method `run()`.
  - "Current document" is written to `workdir / "current.pdf"` before summarizing.

- [ ] **Step 1: Write the failing tests**

`tests/test_summarize_tab.py`:

```python
from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest

from fileconverter import summarize_tab as module
from fileconverter.convert_tab import ConvertTab
from fileconverter.summarize_tab import SummarizeTab


@pytest.fixture
def fake_api(monkeypatch):
    s = module.summarize
    monkeypatch.setattr(s, "get_api_key", lambda: "nvapi-test")
    monkeypatch.setattr(s, "extract_markdown", lambda src: f"text of {src.name}")
    monkeypatch.setattr(s, "summarize", lambda text, style, key, model: f"{style} | {model} | {text}")
    return s


def test_summarize_current_document(qapp, workdir, tall_png, fake_api):
    convert = ConvertTab(workdir)
    convert.add_files([tall_png])
    settle(qapp)
    tab = SummarizeTab(convert, workdir)
    tab.current_radio.setChecked(True)
    tab.run()
    settle(qapp)
    assert tab.result.toPlainText() == f"Short | {fake_api.DEFAULT_MODEL} | text of current.pdf"
    assert tab.run_btn.isEnabled()


def test_summarize_chosen_file_with_style(qapp, workdir, text_pdf, fake_api):
    tab = SummarizeTab(ConvertTab(workdir), workdir)
    tab.source = text_pdf
    next(b for b in tab.style_group.buttons() if b.property("style") == "Bullets").setChecked(True)
    tab.run()
    settle(qapp)
    assert tab.result.toPlainText() == f"Bullets | {fake_api.DEFAULT_MODEL} | text of text.pdf"


def test_failure_reenables_button(qapp, workdir, text_pdf, fake_api, monkeypatch):
    def boom(text, style, key, model):
        raise fake_api.Offline("Cannot reach NVIDIA API")

    monkeypatch.setattr(fake_api, "summarize", boom)
    shown = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda parent, title, text: shown.append(text))
    tab = SummarizeTab(ConvertTab(workdir), workdir)
    tab.source = text_pdf
    tab.run()
    settle(qapp)
    assert shown == ["Cannot reach NVIDIA API"]
    assert tab.run_btn.isEnabled()
    assert tab.result.toPlainText() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_summarize_tab.py -v`
Expected: collection error `ImportError: cannot import name 'summarize_tab' from 'fileconverter'`

- [ ] **Step 3: Implement `fileconverter/summarize_tab.py`**

```python
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
            Path(name).write_text(self.result.toPlainText(), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_summarize_tab.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```powershell
git add fileconverter/summarize_tab.py tests/test_summarize_tab.py
git commit -m "feat: add summarize tab with style choice, key storage, copy and save"
```

---

### Task 9: Main window and entry point (`app.py`, `__main__.py`)

**Files:**
- Create: `fileconverter/app.py`
- Create: `fileconverter/__main__.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `ConvertTab` (Task 7), `SummarizeTab` (Task 8).
- Produces: `MainWindow(QMainWindow)` with `workdir: Path` (session temp dir, deleted on close), `convert_tab`, `summarize_tab`, `tabs`; `main() -> int`. `python -m fileconverter` starts the app.

- [ ] **Step 1: Write the failing tests**

`tests/test_app.py`:

```python
from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

from fileconverter.app import MainWindow


def test_window_has_both_tabs(qapp):
    w = MainWindow()
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Convert", "Summarize"]
    assert w.summarize_tab.convert_tab is w.convert_tab
    w.close()


def test_temp_dir_removed_on_close(qapp, tall_png):
    w = MainWindow()
    workdir = w.workdir
    w.convert_tab.add_files([tall_png])
    settle(qapp)
    assert any(workdir.iterdir())
    w.close()
    assert not workdir.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'fileconverter.app'`

- [ ] **Step 3: Implement `fileconverter/app.py`**

```python
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
        QThreadPool.globalInstance().waitForDone(3000)
        shutil.rmtree(self.workdir, ignore_errors=True)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    return app.exec()
```

- [ ] **Step 4: Create `fileconverter/__main__.py`**

```python
import sys

from fileconverter.app import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: `54 passed` (with LibreOffice installed).

- [ ] **Step 6: Launch the app**

Run: `python -m fileconverter`
Expected: a window titled "FileConverter" with **Convert** and **Summarize** tabs. Then check by hand:

1. Drop two different JPGs on it: two thumbnails appear and the preview shows both pages within about 1 s.
2. Drag the second thumbnail in front of the first with the mouse: the labels renumber (`1 · …`, `2 · …`) and the preview order follows. The automated test only calls `moveRow`, so this is the only check that a real mouse drag works.
3. Close the window.

- [ ] **Step 7: Commit**

```powershell
git add fileconverter/app.py fileconverter/__main__.py tests/test_app.py
git commit -m "feat: add main window with session temp dir and entry point"
```

---

### Task 10: One-file build, README and release check

**Files:**
- Create: `build.ps1`
- Modify: `README.md` (status line, "Features (planned)" heading, remove the "become valid once implementation lands" note, add a Build section note)

**Interfaces:**
- Consumes: `fileconverter/__main__.py` (Task 9).
- Produces: `dist\FileConverter.exe`.

Why each PyInstaller flag is there:
- `--collect-all pypdfium2 pypdfium2_raw`: ships `pdfium.dll`, which is loaded at runtime and invisible to import analysis.
- `--collect-all magika markitdown`: MarkItDown's file-type detector loads its model and config files at runtime.
- `--collect-binaries onnxruntime`: the DLLs magika runs its model with.
- `--hidden-import keyring.backends.Windows`: keyring picks its backend by entry point, which PyInstaller cannot see.
- No `$ErrorActionPreference = "Stop"`: PyInstaller logs to stderr and Windows PowerShell 5.1 would turn that into a fatal error when output is redirected. The exit-code check covers real failures.

- [ ] **Step 1: Create `build.ps1`**

```powershell
# Builds dist\FileConverter.exe (single file, no console window).
# Run from the repo root with the venv active: .\build.ps1
# No $ErrorActionPreference = "Stop": PyInstaller logs to stderr, which
# Windows PowerShell 5.1 would turn into a fatal error. The exit code check covers failures.

python -m PyInstaller --noconfirm --clean --onefile --windowed --name FileConverter `
  --collect-all pypdfium2 `
  --collect-all pypdfium2_raw `
  --collect-all magika `
  --collect-all markitdown `
  --collect-binaries onnxruntime `
  --hidden-import keyring.backends.Windows `
  fileconverter/__main__.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Get-Item dist\FileConverter.exe | Select-Object Name, @{n = "SizeMB"; e = { [math]::Round($_.Length / 1MB) } }
```

- [ ] **Step 2: Build**

Run: `.\build.ps1`
Expected: ends with a table showing `FileConverter.exe` at about 105 MB. `build/`, `dist/` and `*.spec` are already in `.gitignore`.

- [ ] **Step 3: Check the exe opens and closes cleanly**

A one-file exe runs as two processes (unpacker + app), so close it through its window, not by killing the process you started:

```powershell
$p = Start-Process .\dist\FileConverter.exe -PassThru; Start-Sleep 12; $w = Get-Process FileConverter | Where-Object MainWindowTitle -eq "FileConverter"; "window open: $([bool]$w)"; $null = $w.CloseMainWindow(); if ($p.WaitForExit(15000)) { "exit code $($p.ExitCode)" } else { "did not exit" }
```

Expected: `window open: True` then `exit code 0`. (Startup takes 2–5 s because one-file builds unpack to a temp folder.)

- [ ] **Step 4: Update `README.md`**

Replace the status block:

```markdown
> **Status: design phase.** The design spec is approved. Implementation has not started yet. See the [roadmap](#roadmap).
```

with:

```markdown
> **Status: 0.1.0.** Convert, page editing, live preview and AI summaries are implemented. No release has been published yet; build `FileConverter.exe` yourself (below).
```

Rename the heading `## Features (planned)` to `## Features`. Delete the line `> These commands become valid once implementation lands.` In "Getting started (development)", change `pip install -r requirements.txt` to `pip install -r requirements-dev.txt`. After the `.\build.ps1` code block, add:

```markdown
The result is `dist\FileConverter.exe` (about 105 MB). It contains no LibreOffice and no API key: users install LibreOffice themselves for Office files and paste their own NVIDIA key in the Summarize tab.
```

In `## Roadmap`, tick (`- [x]`) every item except the last one, `` `.exe` build and first release ``: publishing a release is the maintainer's decision and not part of this plan.

- [ ] **Step 5: Run the manual GUI checklist**

Run the 10-item checklist in the spec, section 7 ("Manual GUI checklist"), against `dist\FileConverter.exe`. Every item must pass. Item 10 (a machine without Python) can use Windows Sandbox.

- [ ] **Step 6: Commit**

```powershell
git add build.ps1 README.md
git commit -m "build: add one-file PyInstaller build and update README for 0.1.0"
```

---

## Verification record

Checked on 2026-11-20 before writing this plan, against the exact pins above (Windows 11, Python 3.12):

- Every code block in this plan was extracted into an empty directory and the test suite was run task by task. Each task's tests failed before its implementation and passed after it.
- Full suite: 51 passed, 3 skipped (the 3 LibreOffice conversion tests; LibreOffice was not installed on the planning machine, so `office.to_pdf` has **not** been run yet; Task 4 Step 1 closes that).
- Not verified yet, and covered by the plan's own steps: Office conversion with a real LibreOffice (Task 4 Step 1), reordering by mouse drag (Task 9 Step 6), and the 10-item manual GUI checklist (Task 10 Step 5).
- Live NVIDIA call: both models returned a correct one-sentence summary (about 10 s for both).
- `build.ps1` produced a 104 MB `FileConverter.exe` that started and stayed open; a console build of the same flags confirmed MarkItDown text extraction and the Windows keyring backend work inside the frozen exe.
