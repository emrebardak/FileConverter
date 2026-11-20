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
