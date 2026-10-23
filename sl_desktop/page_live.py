"""Jonli savdo paneli: MT5 ulanishi, start/stop, hisob, pozitsiyalar, xavf o'lchagichlari, jonli bitimlar."""
from __future__ import annotations


import datetime as dt
import importlib.util
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QFileDialog)

from . import data as D
from . import widgets as W
from .charts import AttemptsChart, LiveRChart
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
        self.error = W.ErrorPanel()
        self.lay.addWidget(self.error)

        cc = W.Card("Ulanish va boshqaruv", "Login, parol va serverni kiriting — robot o'zi DEMO hisobga kiradi (MT5 terminali o'rnatilgan bo'lishi kerak)")
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
        c2.addWidget(W.label("Hisob (demo): login · parol · server", "text2"))
        self.login = QSpinBox()
        self.login.setRange(0, 2 ** 31 - 1)
        self.login.setSpecialValueText("login (bo'sh — terminaldagi hisob)")
        self.login.setValue(int(s.get("SL_LOGIN") or 0))
        c2.addWidget(self.login)
        ar = QHBoxLayout()
        self.password = QLineEdit(s.get("SL_PASSWORD"))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("parol")
        self.server = QLineEdit(s.get("SL_SERVER"))
        self.server.setPlaceholderText("server (MetaQuotes-Demo)")
        ar.addWidget(self.password, 1)
        ar.addWidget(self.server, 1)
        c2.addLayout(ar)
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
        i0 = self.mode.findData(s.get("SL_MODE"))
        if i0 >= 0:
            self.mode.setCurrentIndex(i0)
        self.mode.currentIndexChanged.connect(self._persist)
        for e in (self.symbol, self.terminal, self.password, self.server):
            e.editingFinished.connect(self._persist)
        self.login.editingFinished.connect(self._persist)
        self.risk.editingFinished.connect(self._persist)
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

        lc2 = W.Card("Uzluksiz o'rganish", "Robot savdo qilib turib ham o'rganadi: har yangi sham saqlanadi, har sikl "
                                           "yangi ma'lumot va variant bilan. Yangi model joriy strategiyadan yaxshi bo'lsagina "
                                           "almashtiriladi")
        self.k_cycles = W.KpiTile("O'rganish sikllari")
        self.k_last = W.KpiTile("Oxirgi sikl")
        self.k_champ = W.KpiTile("Joriy strategiya")
        self.k_data = W.KpiTile("Saqlangan ma'lumot")
        lc2.body.addLayout(W.grid([self.k_cycles, self.k_last, self.k_champ, self.k_data], 4))
        self.achart = AttemptsChart(2.2)
        lc2.body.addWidget(self.achart)
        self.lay.addWidget(lc2)

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

    def _persist(self, *_a) -> None:
        """Maydon o'zgarishi bilan darhol saqlaydi — ishga tushirishni kutmasdan (keyingi safar qayta kiritish shart emas)."""
        if getattr(self, "_loading", False):
            return
        s = self.app.settings
        s.set("SL_MODE", self.mode.currentData() or s.get("SL_MODE"))
        s.set("SL_SYMBOL", self.symbol.text().strip() or "XAUUSD")
        s.set("SL_TERMINAL", self.terminal.text().strip())
        s.set("SL_LOGIN", self.login.value())
        s.set("SL_PASSWORD", self.password.text())
        s.set("SL_SERVER", self.server.text().strip())
        s.set("SL_RISK_PCT", self.risk.value())
        s.save()

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
        s.set("SL_PASSWORD", self.password.text())
        s.set("SL_SERVER", self.server.text().strip())
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
        self.error.clear()
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
        if code != 0:
            self.last_error = last or "kod %d" % code
            self.error.set("Robot to'xtadi (kod %d). %s" % (code, last),
                           W.error_report("Jonli savdo (rejim %s)" % self.mode.currentData(), code, last, self.app,
                                          self.log.toPlainText()))
        self.refresh()
        self.app.refresh_nav()

    def refresh(self) -> None:
        app = self.app
        s = app.settings
        running = app.live.running
        i = self.mode.findData(s.get("SL_MODE"))
        if i >= 0 and not running and self.mode.currentIndex() != i:
            self._loading = True
            self.mode.setCurrentIndex(i)
            self._loading = False
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
        self._learning(st_live)

    def _learning(self, st) -> None:
        """Uzluksiz o'rganish kartasi: jonli holatdan (ishlayotganda) yoki o'rganish jurnalidan."""
        s = self.app.settings
        mode = (st or {}).get("mode") or self.mode.currentData()
        rows = [r for r in D.learn_log(s.state_dir(), 400) if r.get("mode") == mode][-80:]
        pts = [{"no": (r.get("extra") or {}).get("attempt_no", i + 1), "ok": bool(r.get("passed")),
                "t": ((r.get("segments") or {}).get("test") or {}).get("t"),
                "exp": ((r.get("segments") or {}).get("test") or {}).get("exp"),
                "need_t": (r.get("extra") or {}).get("min_t", float(s.get("SL_MIN_T")))} for i, r in enumerate(rows)]
        if self.achart.need((len(rows), rows[-1].get("time") if rows else None)):
            self.achart.show(pts)
        if st:
            busy = st.get("learning")
            self.k_cycles.set(str(st.get("cycles", 0)), "hozir o'rganmoqda…" if busy else
                              ("keyingisi %s" % D.until(st.get("next_learn", 0))) if st.get("continuous") else "uzluksiz o'chiq")
            lr = st.get("last_result") or {}
            if lr:
                self.k_last.set("✓ o'tdi" if lr.get("ok") else "✕ o'tmadi", "%s · t=%s (kerak ≥ %s)" % (
                    D.ago(lr.get("time", 0)), "—" if lr.get("t") is None else "%.2f" % lr["t"],
                    "—" if lr.get("need_t") is None else "%.2f" % lr["need_t"]), "good" if lr.get("ok") else None)
            else:
                self.k_last.set("—", "birinchi sikl davom etmoqda")
            ch = st.get("champ") or {}
            self.k_champ.set(("t = %.2f" % ch["t"]) if ch.get("t") is not None else "—",
                             ("%s joriy qilingan · yangisi undan yaxshi bo'lishi kerak" % D.ago(ch.get("time", 0)))
                             if ch else "tekshirilgan strategiya hali yo'q")
            obs = st.get("spread_obs")
            self.k_data.set("{:,}".format(int(st.get("bars_stored", 0))).replace(",", " ") + " sham",
                            ("jonli spred %.2f (sozlama %.2f)" % (obs, st.get("spread_cfg", 0))) if obs is not None
                            else "spred kuzatilmoqda…")
        else:
            self.k_cycles.set(str(len(rows)), "jurnaldagi sikllar (robot o'chiq)")
            last = rows[-1] if rows else None
            self.k_last.set(("✓ o'tdi" if last.get("passed") else "✕ o'tmadi") if last else "—",
                            last.get("time", "") if last else "")
            self.k_champ.set("—", "robot ishga tushganda ko'rinadi")
            self.k_data.set("—", "")
