"""Asosiy oyna: yon panel, sahifalar, fon ishlar (o'qitish / jonli savdo)."""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import __version__, paths
from .db import Database
from .settings import Settings
from .trainer import Trainer
from .ui import theme as T
from .ui import widgets as W
from .ui.page_data import DataPage
from .ui.page_live import LivePage
from .ui.page_memory import MemoryPage
from .ui.page_overview import OverviewPage
from .ui.page_settings import SettingsPage
from .ui.page_training import TrainingPage
from .ui.update import UpdateManager
from .ui.workers import Job


class NavButton(QPushButton):
    def __init__(self, key: str, text: str):
        super().__init__()
        self.key = key
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(10)
        self.ic = QLabel()
        self.ic.setFixedSize(18, 18)
        self.ic.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.tx = QLabel(text)
        self.tx.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.cnt = QLabel("")
        self.cnt.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.cnt.setFont(T.mono(11))
        for w in (self.ic, self.tx):
            h.addWidget(w)
        h.addStretch(1)
        h.addWidget(self.cnt)
        self.toggled.connect(self._paint)
        self._paint(False)

    def _paint(self, on: bool) -> None:
        self.ic.setPixmap(T.svg(self.key_icon(), T.TEXT if on else T.MUTED, 18))
        self.tx.setStyleSheet("color: %s; font-weight: 500;" % (T.TEXT if on else T.MUTED))
        self.cnt.setStyleSheet("color: %s;" % T.DIM)

    def key_icon(self) -> str:
        return {"overview": "overview", "data": "data", "training": "train", "memory": "memory", "live": "live",
                "settings": "settings"}[self.key]


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None, db: Optional[Database] = None):
        super().__init__()
        self.setWindowTitle("MyOwnRobot")
        self.setWindowIcon(T.app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(1060, 680)
        self.settings = settings or Settings()
        self.db = db or Database(paths.db_path())
        self.live_status: Dict[str, Any] = {}
        self.train_job: Optional[Job] = None
        self.live_job: Optional[Job] = None
        self.updates = UpdateManager(self)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(224)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 12, 16)
        sv.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(8, 4, 8, 18)
        bi = QLabel()
        bi.setPixmap(T.render_svg(open(T._asset("icon.svg"), "rb").read(), 28))
        brand.addWidget(bi)
        bt = QLabel("MyOwnRobot")
        bt.setStyleSheet("font-size: 14px; font-weight: 600;")
        brand.addWidget(bt)
        brand.addStretch(1)
        sv.addLayout(brand)
        self.stack = QStackedWidget()
        self.pages: Dict[str, Any] = {}
        self.nav: Dict[str, NavButton] = {}
        for cls, text in ((OverviewPage, "Umumiy"), (DataPage, "Ma'lumotlar"), (TrainingPage, "O'rganish"),
                          (MemoryPage, "Xotira"), (LivePage, "Jonli savdo"), (SettingsPage, "Sozlamalar")):
            pg = cls(self)
            self.pages[pg.key] = pg
            self.stack.addWidget(pg)
            b = NavButton(pg.key, text)
            b.clicked.connect(lambda _=False, k=pg.key: self.go(k))
            self.nav[pg.key] = b
            sv.addWidget(b)
        sv.addStretch(1)
        self.badge = QPushButton("")
        self.badge.setProperty("kind", "primary")
        self.badge.setVisible(False)
        self.badge.clicked.connect(self._badge_click)
        sv.addWidget(self.badge)
        sv.addSpacing(8)
        foot = QFrame()
        foot.setStyleSheet("QFrame { border-top: 1px solid %s; }" % T.BORDER)
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(8, 10, 8, 0)
        fl.setSpacing(3)
        for t in ("Versiya %s" % __version__, "Faqat DEMO hisob"):
            fl.addWidget(W.label(t, "dim"))
        sv.addWidget(foot)
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.updates.changed.connect(self._sync_badge)
        self.go("overview")

    # ------------------------------------------------------------ navigatsiya
    def go(self, key: str) -> None:
        self.nav[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        self.pages[key].refresh()
        self._counts()

    def changed(self) -> None:
        self.pages[self.current_key()].refresh()
        self._counts()

    def current_key(self) -> str:
        return self.stack.currentWidget().key

    def _counts(self) -> None:
        self.nav["data"].cnt.setText(str(len(self.db.datasets())) if self.db.datasets() else "")
        n = self.db.experience_stats()["n"]
        self.nav["memory"].cnt.setText("{:,}".format(n).replace(",", " ") if n else "")

    def _sync_badge(self) -> None:
        text, tone = self.updates.badge()
        self.badge.setVisible(bool(text))
        self.badge.setText(text)

    def _badge_click(self) -> None:
        if self.updates.state in ("ready", "full_ready"):
            self.updates.restart()
        else:
            self.go("settings")
            self.updates.download()

    # ------------------------------------------------------------ fon ishlar
    def start_training(self) -> None:
        if self.train_job is not None:
            return
        cfg = self.settings.train_cfg()
        db_file = str(paths.db_path())

        def work(emit, stopped):
            db = Database(db_file)
            try:
                return Trainer(db, cfg, emit, stopped).run()
            finally:
                db.close()
        job = Job(work, self)
        tp = self.pages["training"]
        job.event.connect(tp.on_event)
        job.finished_with.connect(self._train_finished)
        self.train_job = job
        tp.on_started(cfg)
        job.start()
        self.changed()

    def _train_finished(self, res, err) -> None:
        self.train_job = None
        self.pages["training"].on_finished(res, err)
        self.changed()

    def stop_training(self) -> None:
        if self.train_job:
            self.train_job.stop()

    def start_live(self, fn) -> None:
        if self.live_job is not None:
            return
        job = Job(fn, self)
        lp = self.pages["live"]
        job.event.connect(lp.on_event)
        job.finished_with.connect(self._live_finished)
        self.live_job = job
        job.start()

    def _live_finished(self, res, err) -> None:
        self.live_job = None
        self.pages["live"].on_finished(res, err)

    def stop_live(self) -> None:
        if self.live_job:
            self.live_job.stop()

    def closeEvent(self, e) -> None:
        busy = [n for n, j in (("O'qitish", self.train_job), ("Jonli savdo", self.live_job)) if j is not None]
        if busy:
            r = QMessageBox.question(self, "Yopish", "%s davom etmoqda. Yopib, to'xtatasizmi?" % " va ".join(busy))
            if r != QMessageBox.Yes:
                e.ignore()
                return
            for j in (self.train_job, self.live_job):
                if j:
                    j.stop()
                    j.wait(8000)
        e.accept()


def run_gui(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("MyOwnRobot")
    app.setStyleSheet(T.STYLE)
    app.setWindowIcon(T.app_icon())
    w = MainWindow()
    if len(argv) > 2 and argv[1] == "--self-test":
        import json
        for k in w.pages:
            w.go(k)
        with open(argv[2], "w", encoding="utf-8") as f:
            json.dump({"version": __version__, "pages": list(w.pages), "source": _source()}, f)
        return 0
    w.show()
    w.updates.start_auto()
    return app.exec()


def _source() -> str:
    import mor
    return str(getattr(mor, "__file__", ""))
