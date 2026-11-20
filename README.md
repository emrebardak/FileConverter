# FileConverter

Open-source Windows desktop app that converts documents and images to PDF. It also lets you edit the result with a live preview and summarize documents with AI.

> **Status: design phase.** The design spec is approved. Implementation has not started yet. See the [roadmap](#roadmap).

## Features (planned)

- **Convert to PDF**
  - PowerPoint: PPT, PPTX, ODP
  - Word: DOC, DOCX, ODT, RTF
  - Excel: XLS, XLSX, ODS
  - Images: JPG, PNG, BMP, TIFF, WEBP, GIF
- **Customize the PDF**
  - Page size, orientation and margins for images
  - Merge many files into one PDF
  - Drag-and-drop page reordering in a thumbnail grid
  - Delete pages
- **Live preview.** The real output PDF updates as you edit.
- **AI summaries** of PDF, DOCX and PPTX files: short, detailed, or bullet points. Uses the free [NVIDIA API catalog](https://build.nvidia.com) with your own key.
- **Single `.exe`.** No Python needed to run it.

## Tech stack

| Concern | Library |
|---|---|
| GUI and PDF viewer | [PySide6](https://doc.qt.io/qtforpython-6/) (Qt 6, QtPdf) |
| Office to PDF | [LibreOffice](https://www.libreoffice.org/), run headless |
| Image to PDF | [Pillow](https://python-pillow.org/) |
| PDF editing | [pypdf](https://github.com/py-pdf/pypdf) |
| Thumbnails | [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) |
| Text extraction | [MarkItDown](https://github.com/microsoft/markitdown) |
| AI summaries | NVIDIA API (OpenAI-compatible endpoint) |
| Key storage | [keyring](https://github.com/jaraco/keyring) (Windows Credential Manager) |
| Packaging | [PyInstaller](https://pyinstaller.org/) |

## Requirements

- Windows 10 or 11
- [LibreOffice](https://www.libreoffice.org/download/) 7.6 or newer. Only needed to convert Office files; images and summaries work without it.
- An NVIDIA API key from [build.nvidia.com](https://build.nvidia.com). Only needed for summaries. Keys are stored in Windows Credential Manager and never shipped with the app.

## Getting started (development)

```powershell
git clone https://github.com/emrebardak/FileConverter.git
cd FileConverter
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m fileconverter
```

Run tests:

```powershell
python -m pytest
```

Build the `.exe`:

```powershell
.\build.ps1
```

> These commands become valid once implementation lands.

## Project layout

```
fileconverter/   application package (office, images, pages, summarize, app)
tests/           pytest suite and small fixture files
docs/            design specs and implementation plans
.github/         issue and pull request templates
```

## Documentation

- [Design spec](docs/superpowers/specs/2026-11-20-file-converter-design.md): architecture, components, data flow, error handling, testing, packaging.
- [Implementation plan](docs/superpowers/plans/2026-11-20-file-converter.md): ten test-first tasks with complete code.

## Roadmap

- [x] Design spec
- [x] Implementation plan
- [ ] Image to PDF with page setup
- [ ] Office to PDF via LibreOffice
- [ ] Page grid: merge, reorder, delete
- [ ] Live PDF preview
- [ ] AI summarizer
- [ ] `.exe` build and first release

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

[MIT](LICENSE). Third-party libraries keep their own licenses. PySide6 is LGPL-3.0. LibreOffice is not bundled.
