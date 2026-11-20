from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest

from fileconverter import summarize
from fileconverter.app import MainWindow


@pytest.fixture(autouse=True)
def no_keyring(monkeypatch):
    monkeypatch.setattr(summarize, "get_api_key", lambda: None)


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
