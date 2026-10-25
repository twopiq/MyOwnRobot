"""Sahifa asosi: sarlavha + ttarkib + yangilash."""
from __future__ import annotations

import time
from typing import Any, Dict

from PySide6.QtWidgets import QVBoxLayout, QWidget


class Page(QWidget):
    key = ""
    title = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.db = win.db
        self.settings = win.settings
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

    def refresh(self) -> None:
        """Sahifa ko'rsatilganda yoki ma'lumot o'zgarganda chaqiriladi."""


def ago(ts: float) -> str:
    d = max(0, time.time() - ts)
    if d < 90:
        return "hozirgina"
    if d < 3600:
        return "%d daq. oldin" % (d // 60)
    if d < 86400:
        return "%d soat oldin" % (d // 3600)
    return "%d kun oldin" % (d // 86400)


def fdate(ts: int, short: bool = False) -> str:
    return time.strftime("%d.%m %H:%M" if short else "%Y-%m-%d %H:%M", time.gmtime(ts))
