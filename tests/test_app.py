from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest
from PySide6.QtCore import QThreadPool

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


def test_temp_dir_removed_even_when_a_task_outlives_close(qapp):
    """A slow conversion that is still writing at close time must not leave the folder behind."""
    import time

    from fileconverter.workers import run_task

    w = MainWindow()
    workdir = w.workdir

    def slow_write():
        time.sleep(4)  # longer than any fixed wait in closeEvent
        workdir.mkdir(exist_ok=True)
        (workdir / "late.pdf").write_bytes(b"%PDF")

    run_task(slow_write, on_done=lambda _: None, on_failed=lambda _: None)
    w.close()
    QThreadPool.globalInstance().waitForDone()
    assert not workdir.exists()
