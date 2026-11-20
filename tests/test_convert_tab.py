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
