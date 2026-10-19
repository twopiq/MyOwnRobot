"""Asosiy oyna: chap menyu, sahifalar, robot jarayonlari va davriy yangilanish."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import __version__
from . import theme
from . import widgets as W
from .charts import Chart
from .page_dashboard import DashboardPage
from .page_help import HelpPage
from .page_journal import JournalPage
from .page_learn import LearnPage
from .page_live import LivePage
from .page_results import ResultsPage
from .page_settings import SettingsPage
from .runner import RobotProcess
from .settings import Settings
from .update_ui import UpdateManager, show_whats_new

NAV = [("dashboard", "🏠   Bosh sahifa"), ("learn", "🧠   O'rganish"), ("results", "📊   Natijalar"),
       ("live", "💹   Jonli savdo"), ("journal", "🗂   Jurnal"), ("settings", "⚙   Sozlamalar"), ("help", "❔   Yordam")]


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None):
        super().__init__()
        self.settings = settings or Settings()
        self.settings.state_dir().mkdir(parents=True, exist_ok=True)
        self.setWindowTitle("MyOwnRobot — o'zi o'rganadigan savdo robot")
        self.resize(1360, 880)
        self.setMinimumSize(1100, 700)
        theme.set_theme(self.settings.ui.get("theme", "dark"))
        QApplication.instance().setStyleSheet(theme.qss(theme.current()))

        self.learn = RobotProcess("learn", self)
        self.live = RobotProcess("live", self)
        self.live.started.connect(self.refresh_nav)
        self.learn.finished.connect(lambda *_: self.refresh_nav())
        self.updates = UpdateManager(self)
        self.updates.changed.connect(self.refresh_nav)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.setCentralWidget(root)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 20, 14, 16)
        sl.setSpacing(4)
        sl.addWidget(W.label("🤖  MyOwnRobot", "brand"))
        sl.addWidget(W.label("O'zi o'rganadigan savdo robot · v" + __version__, "brandsub"))
        sl.addSpacing(18)
        self.nav: Dict[str, QPushButton] = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for key, text in NAV:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            grp.addButton(b)
            sl.addWidget(b)
            self.nav[key] = b
        sl.addStretch(1)
        self.upd_btn = QPushButton("")
        self.upd_btn.setObjectName("nav")
        self.upd_btn.setStyleSheet("QPushButton#nav { background: rgba(57,135,229,0.25); color: #ffffff; font-weight: 600; }")
        self.upd_btn.clicked.connect(self._update_clicked)
        self.upd_btn.setVisible(False)
        sl.addWidget(self.upd_btn)
        self.side_learn = W.StatusPill("O'rganish: yo'q", "idle")
        self.side_live = W.StatusPill("Robot: o'chiq", "idle")
        for x in (self.side_learn, self.side_live):
            x.setStyleSheet("background: transparent;")
            sl.addWidget(x)
        h.addWidget(side)

        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.pages = {"dashboard": DashboardPage(self), "learn": LearnPage(self), "results": ResultsPage(self),
                      "live": LivePage(self), "journal": JournalPage(self), "settings": SettingsPage(self),
                      "help": HelpPage(self)}
        for p in self.pages.values():
            self.stack.addWidget(p)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)
        self.go("dashboard")
        self.updates.start_auto()
        QTimer.singleShot(500, lambda: show_whats_new(self))

    # ------------------------------------------------------------ navigatsiya
    def go(self, key: str) -> None:
        self.nav[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        page.refresh()
        self.refresh_nav()

    def current(self) -> W.Page:
        return self.stack.currentWidget()

    def _tick(self) -> None:
        cur = self.current()
        if not isinstance(cur, (SettingsPage, HelpPage, LearnPage)):
            cur.refresh()
        self.refresh_nav()

    def refresh_all(self) -> None:
        for p in self.pages.values():
            if not isinstance(p, SettingsPage):
                p.refresh()

    def refresh_nav(self) -> None:
        self.side_learn.set("O'rganish davom etmoqda" if self.learn.running else "O'rganish: yo'q",
                            "busy" if self.learn.running else "idle")
        from . import data as D
        st, fresh = D.live_status(self.settings.state_dir())
        text, tone = self.robot_state(st if self.live.running and fresh else None)
        self.side_live.set("Robot: " + text.lower() if self.live.running else "Robot: o'chiq", tone)
        txt, _tone = self.updates.badge()
        self.upd_btn.setText(("⬆   " + txt) if txt else "")
        self.upd_btn.setVisible(bool(txt))

    def _update_clicked(self) -> None:
        if self.updates.state in ("ready", "full_ready"):
            self.updates.restart()
        else:
            self.go("settings")

    def robot_state(self, st) -> Tuple[str, str]:
        """Jonli robot holati -> (yozuv, ohang)."""
        if not self.live.running:
            return ("O'rganmoqda" if self.learn.running else "To'xtatilgan"), ("busy" if self.learn.running else "idle")
        if st is None:
            return "Ulanmoqda…", "busy"
        if st.get("paused"):
            return "Pauza (kill-switch)", "critical"
        if st.get("learning") and not st.get("ready"):
            return "O'rganmoqda", "busy"
        if not st.get("ready") or (st.get("require_pass") and not st.get("validated")):
            return "Strategiya yo'q — savdo qilinmaydi", "warning"
        if st.get("positions"):
            return "Pozitsiyada", "good"
        return "Signal kutmoqda", "good"

    # ------------------------------------------------------------ hodisalar
    def on_learned(self, mode: str, switch: bool = True) -> None:
        self.pages["results"].select_mode(mode)
        self.pages["journal"].chart._key = None
        self.pages["dashboard"].eq._key = None
        self.toast("O'rganish tugadi — natijalar tayyor")
        if switch:
            self.go("results")

    def toast(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 6000)

    def apply_theme(self, name: str) -> None:
        theme.set_theme(name)
        self.settings.ui["theme"] = name
        self.settings.save()
        QApplication.instance().setStyleSheet(theme.qss(theme.current()))
        for ch in self.findChildren(Chart):
            ch._key = None
        for p in self.pages.values():
            p.refresh()
        self.pages["learn"].refresh()
        self.update()

    def closeEvent(self, e) -> None:
        busy = [n for n, p in (("jonli robot", self.live), ("o'rganish", self.learn)) if p.running]
        if busy:
            r = QMessageBox.question(self, "Chiqish", "Hozir %s ishlayapti. Dasturdan chiqilsa u to'xtatiladi "
                                     "(ochiq pozitsiyalar SL/TP bilan terminalda qoladi). Chiqilsinmi?" % " va ".join(busy))
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            if self.live.running:
                self.live.stop(graceful=True)
                self.live.proc.waitForFinished(8000)
                self.live.stop()
            self.learn.stop()
        e.accept()
