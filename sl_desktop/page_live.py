"""Jonli savdo paneli: MT5 ulanishi, start/stop, hisob, pozitsiyalar, xavf o'lchagichlari, jonli bitimlar."""
from __future__ import annotations

import html

import datetime as dt
import importlib.util
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QFileDialog)

from . import data as D
from . import widgets as W
from .charts import LiveRChart
from .settings import MODES


def mt5_available() -> bool:
    return importlib.util.find_spec("MetaTrader5") is not None


class LivePage(W.Page):
    def __init__(self, app):
        super().__init__("Jonli savdo", "Robot MT5 terminali orqali DEMO hisobda savdo qiladi — faqat tekshiruvdan o'tgan "
                                        "strategiya bilan")
        self.app = app
        s = app.settings
        self.pill = W.StatusPill("To'xtatilgan", "idle", big=True)
        self.head_right.addWidget(self.pill)

        self.banner = W.Banner()
        self.lay.addWidget(self.banner)

        cc = W.Card("Ulanish va boshqaruv", "MT5 terminali ochiq va DEMO hisobga kirilgan bo'lishi kerak")
        g = QHBoxLayout()
        g.setSpacing(16)
        c1 = QVBoxLayout()
        c1.addWidget(W.label("Rejim", "text2"))
        self.mode = QComboBox()
        for k, (t, ic, _d) in MODES.items():
            self.mode.addItem("%s  %s" % (ic, t), k)
        c1.addWidget(self.mode)
        c1.addWidget(W.label("Simvol", "text2"))
        self.symbol = QLineEdit(s.get("SL_SYMBOL"))
        c1.addWidget(self.symbol)
        g.addLayout(c1, 1)
        c2 = QVBoxLayout()
        c2.addWidget(W.label("terminal64.exe (ixtiyoriy)", "text2"))
        tr = QHBoxLayout()
        self.terminal = QLineEdit(s.get("SL_TERMINAL"))
        self.terminal.setPlaceholderText("bo'sh — ochiq terminal avtomatik")
        tb = QPushButton("📁")
        tb.setFixedWidth(44)
        tb.clicked.connect(self._browse)
        tr.addWidget(self.terminal, 1)
        tr.addWidget(tb)
        c2.addLayout(tr)
        c2.addWidget(W.label("Hisob raqami (tekshiruv uchun)", "text2"))
        self.login = QSpinBox()
        self.login.setRange(0, 2 ** 31 - 1)
        self.login.setSpecialValueText("tekshirilmaydi")
        self.login.setValue(int(s.get("SL_LOGIN") or 0))
        c2.addWidget(self.login)
        g.addLayout(c2, 2)
        c3 = QVBoxLayout()
        c3.addWidget(W.label("Bitim xavfi", "text2"))
        self.risk = QDoubleSpinBox()
        self.risk.setRange(0.05, 5)
        self.risk.setSingleStep(0.05)
        self.risk.setSuffix(" % balansdan")
        self.risk.setValue(float(s.get("SL_RISK_PCT")))
        c3.addWidget(self.risk)
        self.risk_hint = W.label("", "muted", wrap=True)
        c3.addWidget(self.risk_hint)
        self.risk.valueChanged.connect(self._risk_hint)
        g.addLayout(c3, 1)
        cc.body.addLayout(g)
        br = QHBoxLayout()
        self.start_btn = QPushButton("▶  Robotni ishga tushirish")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("■  To'xtatish")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.clicked.connect(self.stop)
        br.addWidget(self.start_btn)
        br.addWidget(self.stop_btn)
        br.addStretch(1)
        self.learn_info = W.label("", "text2")
        br.addWidget(self.learn_info)
        cc.body.addLayout(br)
        self.lay.addWidget(cc)

        self.k_bal = W.KpiTile("Balans")
        self.k_eq = W.KpiTile("Equity")
        self.k_day = W.KpiTile("Bugungi natija")
        self.k_float = W.KpiTile("Suzuvchi P/L")
        self.lay.addLayout(W.grid([self.k_bal, self.k_eq, self.k_day, self.k_float], 4))

        row = QHBoxLayout()
        row.setSpacing(12)
        gc = W.Card("Himoya", "Chegaraga yetsa robot o'zi to'xtaydi")
        gg = QHBoxLayout()
        self.g_kill = W.Gauge("Kill-switch")
        self.g_day = W.Gauge("Kunlik zarar")
        self.g_spread = W.Gauge("Spred")
        for x in (self.g_kill, self.g_day, self.g_spread):
            gg.addWidget(x)
        gc.body.addLayout(gg)
        row.addWidget(gc, 1)
        sc_ = W.Card("Joriy strategiya")
        self.strat_pill = W.StatusPill("—", "idle")
        sc_.body.addWidget(self.strat_pill)
        self.strat = W.label("—", "text2", wrap=True, plain=True)
        sc_.body.addWidget(self.strat)
        sc_.body.addStretch(1)
        row.addWidget(sc_, 1)
        self.lay.addLayout(row)

        pc = W.Card("Ochiq pozitsiyalar")
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Tiket", "Yo'nalish", "Lot", "Ochilish", "SL", "TP", "Foyda", "Vaqt"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(200)
        pc.body.addWidget(self.table)
        self.no_pos = W.label("Ochiq pozitsiya yo'q", "muted")
        pc.body.addWidget(self.no_pos)
        self.lay.addWidget(pc)

        rc = W.Card("Jonli bitimlar natijasi", "Ustun — har bitim (R), chiziq — kill-switch oynasidagi yig'indi")
        self.rchart = LiveRChart(2.4)
        rc.body.addWidget(self.rchart)
        self.lay.addWidget(rc)

        lc = W.Card("Robot jurnali")
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(220)
        lc.body.addWidget(self.log)
        self.lay.addWidget(lc)
        self.lay.addStretch(1)

        app.live.line.connect(self.log.appendPlainText)
        app.live.finished.connect(self._finished)
        self._risk_hint()
        self.last_error = ""

    def _browse(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "terminal64.exe", "C:/Program Files", "terminal64.exe (terminal64.exe);;*.exe (*.exe)")
        if f:
            self.terminal.setText(f)

    def _risk_hint(self) -> None:
        r = self.risk.value()
        self.risk_hint.setText("10 000 balansda bitta SL ≈ %s zarar" % D.fmt_money(100.0 * r))

    def start(self) -> None:
        s = self.app.settings
        if self.app.live.running:
            return
        if self.app.learn.running:
            QMessageBox.information(self, "Jonli savdo", "Avval o'rganish tugashini kuting.")
            return
        mode = self.mode.currentData()
        s.set("SL_MODE", mode)
        s.set("SL_SYMBOL", self.symbol.text().strip() or "XAUUSD")
        s.set("SL_TERMINAL", self.terminal.text().strip())
        s.set("SL_LOGIN", self.login.value())
        s.set("SL_RISK_PCT", self.risk.value())
        s.save()
        rep = D.latest_report(s.state_dir(), mode)
        if rep is None or not rep.get("passed"):
            msg = ("Bu rejim uchun tekshiruvdan o'tgan strategiya yo'q. Robot ishga tushadi, avval o'zi o'rganadi "
                   "(%d s) va faqat darvozadan o'tsa savdo qiladi. Davom etilsinmi?" % int(s.get("SL_BUDGET_SEC")))
            if QMessageBox.question(self, "Jonli savdo", msg) != QMessageBox.StandardButton.Yes:
                return
        self.log.clear()
        self.last_error = ""
        self.app.live.start([], s.env())
        self.refresh()

    def stop(self) -> None:
        if not self.app.live.running:
            return
        if QMessageBox.question(self, "To'xtatish", "Robot to'xtatilsinmi?\nOchiq pozitsiyalar o'z SL/TP lari bilan "
                                "terminalda qoladi.") == QMessageBox.StandardButton.Yes:
            self.app.live.stop(graceful=True)
            self.pill.set("To'xtatilmoqda…", "busy")

    def _finished(self, code: int, last: str) -> None:
        if code not in (0,) and last:
            self.last_error = last
        self.refresh()
        self.app.refresh_nav()

    def refresh(self) -> None:
        app = self.app
        s = app.settings
        running = app.live.running
        i = self.mode.findData(s.get("SL_MODE"))
        if i >= 0 and not running:
            self.mode.setCurrentIndex(i)
        for w in (self.mode, self.symbol, self.terminal, self.login, self.risk):
            w.setEnabled(not running)
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        st, fresh = D.live_status(s.state_dir())
        st_live = st if running and fresh else None
        text, tone = app.robot_state(st_live)
        self.pill.set(text, tone)

        if not mt5_available():
            self.banner.set("MetaTrader5 Python kutubxonasi topilmadi%s. Jonli savdo faqat Windows'da, MT5 terminali bilan "
                            "ishlaydi: pip install MetaTrader5. O'rganish va natijalar MT5siz ishlaydi." % (
                                "" if sys.platform == "win32" else " (bu kompyuter Windows emas)"), "warning")
        elif self.last_error and not running:
            self.banner.set("Robot to'xtadi: " + html.escape(self.last_error), "critical")
        elif running and st is not None and not fresh:
            self.banner.set("Ulanmoqda… (MT5 terminali javobini kutish)", "info")
        else:
            self.banner.set("")

        cur = (st_live or {}).get("currency", "")
        if st_live:
            self.k_bal.set(D.fmt_money(st_live["balance"], cur), "%s · %s" % (st_live.get("server", ""), st_live.get("login", "")))
            self.k_eq.set(D.fmt_money(st_live["equity"], cur), "")
            de = st_live["equity"] - st_live.get("day_equity", st_live["equity"]) if st_live.get("day_equity") else 0.0
            pct = de / st_live["day_equity"] * 100 if st_live.get("day_equity") else 0.0
            self.k_day.set(D.fmt_money(de, cur), "%+.2f%%" % pct, "good" if de > 0 else "critical" if de < 0 else None)
            pl = sum(p.get("profit", 0) for p in st_live.get("positions", []))
            self.k_float.set(D.fmt_money(pl, cur), "%d ta pozitsiya" % len(st_live.get("positions", [])))
            self.learn_info.setText("Oxirgi o'rganish: %s · keyingisi: %s" % (D.ago(st_live.get("last_learn", 0)),
                                                                           D.until(st_live.get("next_learn", 0))))
        else:
            for k in (self.k_bal, self.k_eq, self.k_day, self.k_float):
                k.set("—", "robot ishlamayapti" if not running else "ma'lumot kutilmoqda")
            self.learn_info.setText("")

        # o'lchagichlar
        win, lim = int(s.get("SL_KILL_WINDOW")), float(s.get("SL_KILL_SUM_R"))
        rs = (st_live or {}).get("rs", [])
        if st_live:
            tot = sum(rs[-win:])
            self.g_kill.set(max(0.0, -tot) / max(1e-9, -lim), "%+.1fR" % tot, "oxirgi %d · chegara %.0fR" % (len(rs[-win:]), lim))
            d0, eq = st_live.get("day_equity", 0), st_live.get("equity", 0)
            lp = max(0.0, (d0 - eq) / d0 * 100) if d0 else 0.0
            dl = float(st_live.get("max_daily_loss_pct", 3))
            self.g_day.set(lp / dl, "%.2f%%" % lp, "limit %.1f%%" % dl)
            sp, ms = st_live.get("spread", 0), st_live.get("max_spread", 1)
            self.g_spread.set(sp / ms if ms else 0, "%.2f" % sp, "maks. %.2f" % ms)
        else:
            self.g_kill.set(0, "—", "chegara %.0fR" % lim)
            self.g_day.set(0, "—", "limit %.1f%%" % float(s.get("SL_MAX_DAILY_LOSS_PCT")))
            self.g_spread.set(0, "—", "maks. %.2f" % float(s.get("SL_MAX_SPREAD")))

        # strategiya
        if st_live:
            if st_live.get("learning") and not st_live.get("ready"):
                self.strat_pill.set("O'rganmoqda…", "busy")
            elif not st_live.get("ready"):
                self.strat_pill.set("Strategiya yo'q — savdo qilinmaydi", "warning")
            elif st_live.get("paused"):
                self.strat_pill.set("Pauza: kill-switch ishladi", "critical")
            elif st_live.get("validated"):
                self.strat_pill.set("Tekshirilgan strategiya", "good")
            else:
                self.strat_pill.set("Tekshirilmagan (tadqiqot rejimi)", "serious")
            self.strat.setText(st_live.get("strategy") or "—")
        else:
            rep = D.latest_report(s.state_dir(), self.mode.currentData())
            if rep and rep.get("passed"):
                self.strat_pill.set("Saqlangan: tekshirilgan", "good")
            elif rep:
                self.strat_pill.set("Oxirgi o'rganish darvozadan o'tmagan", "warning")
            else:
                self.strat_pill.set("Hali o'rganilmagan", "idle")
            self.strat.setText((rep or {}).get("strategy") or "—")

        # pozitsiyalar
        pos = (st_live or {}).get("positions", [])
        self.table.setRowCount(len(pos))
        for r, p in enumerate(pos):
            vals = [str(p["ticket"]), "▲ BUY" if p["dir"] > 0 else "▼ SELL", "%.2f" % p["volume"], "%.2f" % p["price"],
                    "%.2f" % p["sl"], "%.2f" % p["tp"], D.fmt_money(p["profit"]),
                    dt.datetime.utcfromtimestamp(p["time"]).strftime("%m-%d %H:%M")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
        self.table.setVisible(bool(pos))
        self.no_pos.setVisible(not pos)
        if self.rchart.need((tuple(rs), lim, win)):
            self.rchart.show(rs, lim, win)
