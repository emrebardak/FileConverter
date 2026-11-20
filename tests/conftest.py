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
