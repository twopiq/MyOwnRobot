"""Fon oqimlari: o'qitish, import, jonli savdo. UI qotmaydi; hodisalar signal bilan keladi."""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal


class Job(QThread):
    event = Signal(object)
    finished_with = Signal(object, object)         # natija, xato

    def __init__(self, fn: Callable[[Callable[[Any], None], Callable[[], bool]], Any], parent=None):
        super().__init__(parent)
        self.fn = fn
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self) -> None:
        try:
            res = self.fn(self.event.emit, self._stop.is_set)
            self.finished_with.emit(res, None)
        except Exception as e:  # noqa: BLE001
            self.finished_with.emit(None, e)
