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
