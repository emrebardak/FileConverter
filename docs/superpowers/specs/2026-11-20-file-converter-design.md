# FileConverter — Design Spec

Date: 2026-11-20
Status: Approved design, ready for implementation planning

## 1. Goal

A Windows desktop app that:

1. Converts Office documents and images **into PDF** (PPT/PPTX, DOC/DOCX, XLS/XLSX, ODT/ODP/ODS, RTF, JPG/PNG/BMP/TIFF/WEBP/GIF).
2. Lets the user **customize the PDF**: page setup for images, merge several files into one PDF, reorder pages, delete pages.
3. Shows a **live preview** of the output PDF that updates as the user edits.
4. **Summarizes** a PDF, DOCX, or PPTX with an AI model through NVIDIA's free API.

Ships as a single `.exe` that others can double-click without installing Python.

### Non-goals

- Converting **out of** PDF (PDF to Word, PDF to images).
- Watermarks, page numbers, compression, passwords.
- OCR for scanned PDFs.
- Chat or Q&A with a document.
- Bundling LibreOffice or any API key inside the `.exe`.

## 2. Tech stack

| Concern | Choice | License |
|---|---|---|
| Language | Python 3.12 | — |
| GUI | PySide6 (Qt 6), including `QtPdf` / `QtPdfWidgets` | LGPL-3.0 |
| Office to PDF | LibreOffice, run headless (installed separately by the user) | MPL-2.0 |
| Image to PDF | Pillow | MIT-CMU |
| PDF merge / reorder / delete / write | pypdf | BSD-3-Clause |
| Page thumbnails | pypdfium2 | BSD-3 / Apache-2.0 |
| Text extraction for summaries | `markitdown[pdf,docx,pptx]` (exact version pinned) | MIT |
| AI summaries | NVIDIA API catalog, OpenAI-compatible endpoint, called with stdlib `urllib` | NVIDIA terms |
| API key storage | `keyring` (Windows Credential Manager) | MIT |
| Packaging | PyInstaller `--onefile --windowed` | GPL with bootloader exception |
| Tests | pytest | MIT |

All runtime libraries are permissive or LGPL, so the `.exe` can be shared freely. PyMuPDF was rejected because it is AGPL.

Exact dependency versions are pinned in `requirements.txt` at implementation time.

## 3. Project layout

```
FileConverter/
  fileconverter/
    __init__.py
    __main__.py     # entry point: python -m fileconverter
    office.py       # find soffice; Office file -> PDF
    images.py       # image -> PDF with page setup
    pages.py        # page model, thumbnails, assemble PDF bytes, save
    summarize.py    # file -> Markdown -> NVIDIA API -> summary
    workers.py      # run_task(): QThreadPool worker, results back on the UI thread
    preview.py      # PdfPreview widget: QPdfView loaded from memory
    convert_tab.py  # Convert tab: grid, page setup, status, save
    summarize_tab.py# Summarize tab
    app.py          # main window and main()
  tests/
    conftest.py     # generates tiny fixture files (docx, pptx, png, jpg, pdf) per test
    qt_helpers.py   # headless qapp fixture and settle() for GUI tests
    test_images.py  test_pages.py  test_office.py  test_summarize.py
    test_preview.py test_convert_tab.py test_summarize_tab.py test_app.py
  requirements.txt
  requirements-dev.txt
  build.ps1         # PyInstaller one-file build
  README.md         # how to run, install LibreOffice, get an NVIDIA key
```

Rule: `office.py`, `images.py`, `pages.py`, and `summarize.py` never import Qt. They are plain functions, testable without a GUI. Only the five GUI modules import Qt; each one is small enough to review on its own.

## 4. Components

### 4.1 `office.py`

```python
OFFICE_EXTS = {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".odp", ".ods", ".rtf"}

def find_soffice() -> Path | None
def to_pdf(src: Path, workdir: Path, timeout: int = 120) -> Path
```

- `find_soffice()` searches, in order: `PATH` (`soffice.exe`), `C:\Program Files\LibreOffice\program\soffice.exe`, `C:\Program Files (x86)\LibreOffice\program\soffice.exe`, then the registry key `HKLM\SOFTWARE\LibreOffice\UNO\InstallPath`. Returns `None` if none are found.
- `to_pdf()` runs:
  `soffice --headless --norestore -env:UserInstallation=file:///<unique temp profile dir> --convert-to pdf --outdir <unique temp out dir> <src>`
  - A **unique profile dir per run** prevents clashes with a LibreOffice window the user already has open.
  - A **unique out dir per run** prevents name collisions (`a.docx` and `a.pptx` both produce `a.pdf`).
  - Runs through `subprocess.run(..., timeout=timeout)`. On timeout, the process is killed and `ConversionError("timed out")` is raised.
  - A non-zero exit code or a missing output file raises `ConversionError` with LibreOffice's stderr.
- Raises `LibreOfficeMissing` if `find_soffice()` returns `None`.

### 4.2 `images.py`

```python
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}

@dataclass(frozen=True)
class PageSetup:
    size: Literal["A4", "Letter", "Fit"] = "A4"
    orientation: Literal["Auto", "Portrait", "Landscape"] = "Auto"
    margin_mm: float = 10.0

def to_pdf(src: Path, setup: PageSetup, workdir: Path) -> Path
```

- A4 = 210×297 mm. Letter = 215.9×279.4 mm. Rendering uses 300 DPI.
- `Fit`: the page is exactly the image size plus margins. Orientation is ignored.
- `Auto` orientation: landscape if the image is wider than it is tall, else portrait.
- The image is scaled to fit inside the margins, aspect ratio preserved, centered on a white page.
- Transparency (PNG/WEBP/GIF) is flattened onto white. GIF uses the first frame only. EXIF rotation is applied (`ImageOps.exif_transpose`).
- Saved with Pillow's PDF writer at `resolution=300`.
- **Page setup applies to images only.** Office documents keep their own page size and layout.

### 4.3 `pages.py`

```python
@dataclass(frozen=True)
class Page:
    source_pdf: Path   # intermediate PDF in the session temp dir
    index: int         # 0-based page index in source_pdf
    origin: Path       # original file the user added (for labels/colour tags)

def pages_of(pdf: Path, origin: Path) -> list[Page]
def thumbnail(page: Page, max_px: int = 160) -> PIL.Image.Image
def to_bytes(pages: list[Page]) -> bytes
def save(pages: list[Page], out: Path) -> None
```

- `thumbnail` renders through pypdfium2.
- `to_bytes` builds the output with `pypdf.PdfWriter` in list order and returns the bytes. Both the live preview and `save` use it.
- `save` writes `to_bytes()` to a temp file next to `out`, then `os.replace`s it onto `out`. A failed save never leaves a half-written file.
- An empty `pages` list raises `ValueError`.

### 4.4 `summarize.py`

```python
SUMMARY_EXTS = {".pdf", ".docx", ".pptx"}
Style = Literal["Short", "Detailed", "Bullets"]

def extract_markdown(src: Path) -> str
def chunk(text: str, max_chars: int = 100_000) -> list[str]
def summarize(text: str, style: Style, api_key: str, model: str) -> str
def get_api_key() -> str | None
def set_api_key(key: str) -> None
```

- `extract_markdown` uses `MarkItDown().convert(str(src)).text_content`. If the stripped result is empty, it raises `NoTextFound` (likely a scanned PDF).
- `chunk` splits on paragraph boundaries (`\n\n`) into pieces of at most `max_chars`. A single paragraph longer than the limit is hard-split.
- `summarize`:
  - One chunk: a single request.
  - Several chunks: each chunk is summarized with the "Detailed" prompt, then the joined chunk summaries are summarized once more with the requested `style` (map-reduce).
- HTTP call: `POST https://integrate.api.nvidia.com/v1/chat/completions` with header `Authorization: Bearer <key>` and JSON body `{"model", "messages": [system, user], "max_tokens": 2048, "temperature": 0.2}`, sent with `urllib.request`. The summary is `choices[0].message.content`. Timeout 120 s.
- Style prompts (system message):
  - Short: "Summarize the document in one paragraph of at most 5 sentences."
  - Detailed: "Summarize the document in several paragraphs covering every main section."
  - Bullets: "Summarize the document as 5–10 concise bullet points."
  - All three add: "Use only information from the document. Reply in the document's language."
- Model choice (checked 2026-11-20 against the live list at `GET https://integrate.api.nvidia.com/v1/models`):
  - **Default: `nvidia/nemotron-3-ultra-550b-a55b`.** NVIDIA's own flagship, so it is the least likely to vanish from the catalog. Its 1M-token context means almost any document fits in one request, which matters under the 40 requests/minute limit. It is a 55B-active MoE, so it is fast for its quality.
  - **Fast alternative: `nvidia/nemotron-3.5-lightning-30b-a3b`.** A small 3B-active MoE for quick summaries.
  - Rejected: `moonshotai/kimi-k3.1-pro` and `mistralai/mistral-large-4-1t-a52b` (larger and slower, with no gain for summaries); `nvidia/nemotron-3.5-super-vl-120b-a12b` (early access); Gemma, GLM and MiniMax "flash" models (third-party, so they are more likely to rotate out).
  - The UI offers both models in an editable combo box, so users can type any other model ID from the catalog.
- Model output: reasoning models may wrap their thinking in `<think>…</think>`. `summarize` strips any such block before returning.
- API key: `get_api_key()` returns the `NVIDIA_API_KEY` env var if set, else `keyring.get_password("FileConverter", "nvidia")`. `set_api_key` stores the key with keyring. The key is never written to disk in plain text, never logged, and never bundled.
- Errors map to typed exceptions: HTTP 401/403 to `BadApiKey`, 429 to `RateLimited`, `URLError` / timeout to `Offline`, any other HTTP error to `ApiError(status, body)`.

Free-tier notes for the README: about 40 requests/minute, intended for prototyping, and every user brings their own `nvapi-…` key from build.nvidia.com.

### 4.5 GUI (`workers.py`, `preview.py`, `convert_tab.py`, `summarize_tab.py`, `app.py`)

Main window with two tabs.

**Convert tab** (horizontal splitter):

- **Left side**
  - Drop zone and "Add files…" button. The button accepts every extension in `OFFICE_EXTS | IMAGE_EXTS`.
  - Thumbnail grid: `QListWidget` in `ListMode` with left-to-right wrapping flow (looks like an icon grid) and `InternalMove` drag-drop. `IconMode` was rejected because its free-move reordering is unreliable. Each item stores an integer page id that maps to its `Page`.
  - Under each thumbnail: page number plus source file name. A colour tag marks each origin file.
  - Delete key removes the selected pages. Multi-select uses Ctrl/Shift.
  - Page setup panel: Size combo (A4/Letter/Fit), Orientation combo (Auto/Portrait/Landscape), Margin spin box (0–50 mm).
  - Status list: one row per added file, showing Converting… / Done / Failed: reason.
  - "Save PDF…" button.
- **Right side**
  - Live viewer: `QPdfView` (multi-page, continuous scroll) fed by a `QPdfDocument` that loads from a `QBuffer` holding `pages.to_bytes()`.
  - Zoom −/+ buttons and Fit-width.
  - Empty state: "Add files to see preview".
  - Clicking a thumbnail jumps the viewer to that page through `pageNavigator().jump(...)`.

**Summarize tab**

- Source picker: "Choose file…" (PDF/DOCX/PPTX) or "Use current document" (the Convert tab's pages, via `to_bytes()` written to a temp PDF).
- Style radio buttons: Short / Detailed / Bullet points.
- "Summarize" button, which is disabled while a request runs.
- Read-only result text box, plus "Copy" and "Save…" (`.txt` / `.md`) buttons.
- Settings row: masked API key field with a "Save key" button, a model name field, and a link to build.nvidia.com.

**Threading:** every conversion, thumbnail batch, and summary runs in a `QThreadPool` worker. Results come back to the UI thread through signals. The UI never blocks.

## 5. Data flow

### 5.1 Convert

1. On startup the app creates one session temp dir (`tempfile.mkdtemp`) and deletes it on exit.
2. The user adds files. Each file gets a worker:
   - Office file: `office.to_pdf`.
   - Image: `images.to_pdf` with the current `PageSetup`.
   - Other extension: skipped, with a status message.
3. When a worker finishes, its `pages_of(pdf)` are appended to the end of the grid and thumbnails render in the background. Files finish in any order; each one's pages append when it finishes.
4. **Page setup change:** every image origin is re-converted with the new setup. Its pages are replaced in place, keeping their grid positions. Office pages are untouched.
5. **Preview refresh:** any grid change (add, reorder, delete, re-convert) restarts a 500 ms single-shot `QTimer`. When it fires, the app calls `to_bytes(current grid order)` and reloads `QPdfView` from memory, keeping the current scroll position when possible.
6. **Save PDF…:** a file dialog opens and asks for confirmation if the target exists. Then `pages.save(grid order, path)` runs and the status bar shows "Saved to …".

### 5.2 Summarize

1. Source is a chosen file or the current document. The current document is written to `<session tmp>/current.pdf`.
2. `extract_markdown`, then `chunk`, then `summarize` all run in a worker.
3. The result shows in the text box. Copy places it on the clipboard. Save writes UTF-8 text.

## 6. Error handling

| Situation | Behaviour |
|---|---|
| LibreOffice not installed | Office files are refused. Dialog: "LibreOffice is required for Office files", with a download link (libreoffice.org). Images and summarizing still work. |
| Office conversion fails or exceeds 120 s | That file is marked "Failed: reason". Other files continue. |
| Unsupported extension | Skipped, with a status message. |
| Corrupt image | That file is marked "Failed: cannot read image". |
| Save fails (locked or read-only target) | Error dialog. Grid and preview are unchanged and the temp file is cleaned up. |
| Save with empty grid | Save button is disabled. |
| No text in source | "No text found - scanned PDF? OCR is not supported." |
| No API key | Prompt to enter a key, with a link to build.nvidia.com. |
| `BadApiKey` | "API key rejected - check it on build.nvidia.com." |
| `RateLimited` | "Rate limited - wait a minute and try again." |
| `Offline` | "Cannot reach NVIDIA API - check your internet connection." |
| `ApiError` | Shows the status code and the first 200 characters of the body. |

No error ever stops other files that are in progress. No error discards the user's grid.

## 7. Testing

pytest, run with `python -m pytest`. Fixture files are generated per test by `tests/conftest.py`, so the repo holds no binary fixtures. GUI tests run headless (`QT_QPA_PLATFORM=offscreen`).

- `test_images.py`
  - A4 portrait gives a page of 595×842 pt (±1).
  - Letter gives 612×792 pt (±1).
  - Landscape swaps the dimensions.
  - `Auto` picks landscape for a wide image.
  - `Fit` page size matches the image plus margins.
  - A transparent PNG converts without error.
- `test_pages.py`
  - `pages_of` returns the correct count.
  - `to_bytes` with reordered and deleted pages gives the expected page count and order. Order is checked by page text or size marker.
  - `save` writes atomically. An empty list raises.
  - `thumbnail` returns an image no larger than `max_px`.
- `test_office.py`
  - `find_soffice` returns a path or `None` without raising.
  - The DOCX and PPTX fixtures convert to a valid PDF with at least one page.
  - The conversion tests are marked `skipif(find_soffice() is None)`. LibreOffice is **not** installed on the dev machine yet, so install it before verifying them.
- `test_summarize.py`
  - `chunk` respects `max_chars` and splits on paragraphs.
  - `extract_markdown` on the PDF fixture returns non-empty text.
  - `summarize` against a stubbed `urllib.request.urlopen`: a single chunk makes one call, several chunks make N+1 calls.
  - 401 raises `BadApiKey`, 429 raises `RateLimited`, `URLError` raises `Offline`.
  - No test uses a real key or network.

**Manual GUI checklist** (run before each release):

1. Drag in a DOCX, a PPTX, and two JPGs. All convert and thumbnails appear.
2. Drag a page to a new position. The preview updates within about 1 s.
3. Select two pages and press Delete. They disappear from the grid and the preview.
4. Change the page size to Letter and the margin to 25 mm. Only image pages change.
5. Click a thumbnail. The viewer jumps to that page.
6. Save PDF. Open the result in another viewer and check it matches the preview.
7. Rename LibreOffice's folder temporarily. Adding a DOCX shows the install hint, and images still work.
8. Summarize the saved PDF in all three styles. Summarize a PPTX directly.
9. Enter a wrong API key. The "API key rejected" message appears.
10. Run the built `.exe` on a machine without Python.

## 8. Packaging

`build.ps1`:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FileConverter `
  --collect-all pypdfium2 `
  --collect-all pypdfium2_raw `
  --collect-all magika `
  --collect-all markitdown `
  --collect-binaries onnxruntime `
  --hidden-import keyring.backends.Windows `
  fileconverter/__main__.py
```

- PyInstaller's PySide6 hooks include `QtPdf` / `QtPdfWidgets` once `app.py` imports them. Verify that the built `.exe` shows the preview.
- Measured size: 104 MB (PyInstaller 6.22.3, 2026-11-20). Expected startup is 2–5 s, because onefile unpacks to a temp folder.
- The `.exe` contains **no** LibreOffice and **no** API key. The README tells users to install LibreOffice for Office files and to paste their own NVIDIA key.
- If a collect flag proves unnecessary or another one is missing, adjust `build.ps1` and note why in a comment.

## 9. Prerequisites for the developer

- Python 3.12 (already installed).
- LibreOffice 7.6 or newer from libreoffice.org. Needed to run the Office conversion tests and the manual checklist.
- An NVIDIA API key from build.nvidia.com, only for manual summary testing.
- `pip install -r requirements.txt`, plus `pytest` and `pyinstaller` for development.
