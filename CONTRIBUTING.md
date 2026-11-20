# Contributing to FileConverter

Thanks for helping. This guide keeps the project consistent.

## Before you start

- Check [open issues](https://github.com/emrebardak/FileConverter/issues) to see if someone is already on it.
- For anything bigger than a small fix, open an issue first and agree on the approach.
- Read the [design spec](docs/superpowers/specs/2026-11-20-file-converter-design.md). New features should fit its architecture.

## Setup

```powershell
git clone https://github.com/emrebardak/FileConverter.git
cd FileConverter
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install [LibreOffice](https://www.libreoffice.org/download/) if you plan to touch the Office conversion code or run its tests.

## Workflow

1. Fork the repo and create a branch from `main`, named like `feat/page-rotation` or `fix/png-transparency`.
2. Keep changes focused. One topic per pull request.
3. Add or update tests for any logic change.
4. Run `python -m pytest`. All tests must pass. Office tests are skipped automatically if LibreOffice is missing.
5. Open a pull request using the template.

## Code rules

- Python 3.12. Use type hints on public functions.
- Only `fileconverter/app.py` may import Qt. Core modules (`office`, `images`, `pages`, `summarize`) stay plain Python so they are testable without a GUI.
- Long-running work runs in worker threads, never on the UI thread.
- Before adding a new dependency, check that its license is permissive (MIT, BSD, Apache) or LGPL. AGPL and GPL libraries can't be bundled.
- Never commit API keys, real user documents, or generated `.exe` files.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add page rotation to grid
fix: keep PNG transparency white on A4 pages
docs: explain LibreOffice install
test: cover chunking edge cases
```

## Reporting bugs and requesting features

Use the issue templates. For a bug, include steps to reproduce, the expected and actual result, your Windows version, and your LibreOffice version if relevant.
