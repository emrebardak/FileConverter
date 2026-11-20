"""Run blocking work on Qt's thread pool and get the result back on the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as e:  # report every failure to the UI thread
            self.signals.failed.emit(str(e) or type(e).__name__)
        else:
            self.signals.done.emit(result)


_live_tasks: set[_Task] = set()  # keeps signal objects alive until delivered


def run_task(fn, *args, on_done, on_failed) -> None:
    """Run fn(*args) on the global thread pool; callbacks run on the UI thread."""
    task = _Task(fn, args)
    _live_tasks.add(task)

    def finish(callback, value):
        _live_tasks.discard(task)
        callback(value)

    task.signals.done.connect(lambda v: finish(on_done, v))
    task.signals.failed.connect(lambda m: finish(on_failed, m))
    task.setAutoDelete(False)
    QThreadPool.globalInstance().start(task)
