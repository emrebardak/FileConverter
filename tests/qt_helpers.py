"""Shared helpers for the headless GUI tests. Import before any other Qt import."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window, works in CI

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    # Delete every widget while the app still exists. Left to interpreter shutdown,
    # they are destroyed in random order and the process crashes on exit.
    QThreadPool.globalInstance().waitForDone(15000)
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)


def settle(qapp, rounds: int = 6) -> None:
    """Let worker threads finish and deliver their queued signals."""
    for _ in range(rounds):
        QThreadPool.globalInstance().waitForDone(15000)
        qapp.processEvents()
