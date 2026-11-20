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
