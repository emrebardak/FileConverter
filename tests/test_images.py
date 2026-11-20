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
