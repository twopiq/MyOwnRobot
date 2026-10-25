from __future__ import annotations

import time
from typing import Any, Dict

from PySide6.QtWidgets import QGridLayout, QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget

from .. import paths
from ..agent import Agent
from ..db import Database
from ..live import Broker, LiveRunner
from ..trainer import _currencies_of
from . import theme as T
from . import widgets as W
from .page import Page, fdate
from .workers import Job


class LivePage(Page):
    key, title = "live", "Jonli savdo"

    def __init__(self, win):
        super().__init__(win)
        self.p_state = W.pill("To'xtagan")
        self.b_start = W.button("Savdoni boshlash", "primary", on=self.start)
        self.b_stop = W.button("To'xtatish", "danger", on=self.stop)
        self.b_stop.setVisible(False)
        self.b_set = W.button("MT5 sozlamalari", on=lambda: win.go("settings"))
        self.root.addWidget(W.page_header(self.title, [self.p_state, W.pill("Faqat DEMO hisob")], [self.b_set, self.b_stop, self.b_start]))
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(24, 20, 24, 20)
        g.setSpacing(16)
        g.setColumnStretch(0, 10)
        g.setColumnStretch(1, 17)
        self.root.addWidget(body, 1)
        c1 = W.Card("Hisob va siyosat")
        names = ("Hisob", "Server", "Balans", "Equity", "Siyosat", "Darvoza", "Pozitsiya", "Xavf nazorati")
        self.kv = {n: W.KV(n, "—") for n in names}
        for w in self.kv.values():
            c1.add(w)
        g.addWidget(c1, 0, 0, 2, 1)
        c2 = W.Card("Qarorlar")
        self.table = W.Table(["Sham (UTC)", "Qaror", "Q: kutish / buy / sell / yopish", "Izoh"], mono_cols=(0, 2), stretch_col=3)
        c2.add(self.table, 1)
        g.addWidget(c2, 0, 1)
        self.log = W.log_view(130, 300)
        c3 = W.Card("Jurnal")
        c3.add(self.log)
        g.addWidget(c3, 1, 1)
        self.rows = []

    # ------------------------------------------------------------ boshqaruv
    def start(self) -> None:
        pol = self.db.latest_policy()
        if not pol:
            QMessageBox.information(self, "Siyosat yo'q", "Avval agentni o'rgating (O'rganish sahifasi).")
            return
        if not pol["deployed"] and not self.settings["allow_unvalidated"]:
            QMessageBox.warning(self, "Darvozadan o'tmagan", "Oxirgi siyosat tekshiruv darvozasidan o'tmagan "
                                "(test davrida foyda isbotlanmagan), shuning uchun savdo bloklangan.\n\n"
                                "Faqat tadqiqot uchun: Sozlamalar → Jonli savdo → «Tekshiruvdan o'tmagan siyosat».")
            return
        cfg = self.settings.live_cfg()
        db_file = str(paths.db_path())

        def work(emit, stopped):
            broker = Broker(cfg)
            info = broker.connect()
            emit({"type": "connected", **info})
            db = Database(db_file)
            try:
                ev = None
                e = db.get_events(_currencies_of(cfg.symbol) or None, 3)
                if len(e):
                    ev = e["ts"].to_numpy()
            finally:
                db.close()
            LiveRunner(cfg, pol["path"], broker, ev, emit, stopped).run()
            broker.shutdown()
            return None
        self.rows = []
        self.table.fill([])
        self.win.start_live(work)
        self.b_start.setVisible(False)
        self.b_stop.setVisible(True)
        self.p_state.setText("Ulanmoqda…")

    def stop(self) -> None:
        self.win.stop_live()
        self.b_stop.setEnabled(False)
        self.p_state.setText("To'xtatilmoqda…")

    def on_event(self, e: Dict[str, Any]) -> None:
        t = e.get("type")
        st = self.win.live_status
        if t == "connected":
            st.update(connected=True, running=True, balance=e["balance"], equity=e["equity"], currency=e["currency"])
            self.kv["Hisob"].set(str(e["login"]))
            self.kv["Server"].set(e["server"])
            self.p_state.setText("Ishlayapti")
            self.win.changed()
        elif t == "account":
            st.update(balance=e["balance"], equity=e["equity"])
            self.kv["Balans"].set("%.2f" % e["balance"])
            self.kv["Equity"].set("%.2f" % e["equity"])
        elif t == "decision":
            self.rows.insert(0, [fdate(e["ts"]), (e["action"], "up" if e["action"] == "BUY" else ("down" if e["action"] == "SELL" else "")),
                                 " / ".join("%+.2f" % x for x in e["q"]), e.get("note", "")])
            self.table.fill(self.rows[:100], [16, 10, 30, 30])
            self.kv["Xavf nazorati"].set(e["blocked"] or "faol", "warn" if e["blocked"] else "up")
            if "opened" in e:
                self.log.appendPlainText("Ochildi: %s lot=%.2f SL=%.5g" % (e["action"], e["lots"], e["sl"]))
        elif t == "trade_closed":
            self.log.appendPlainText("Yopildi: %+.2fR" % e["r"])
        elif t == "error":
            self.log.appendPlainText("Xato: %s" % e["msg"])
        elif t == "log":
            self.log.appendPlainText(e["msg"])

    def on_finished(self, res, err) -> None:
        self.win.live_status.update(running=False, connected=False)
        self.b_start.setVisible(True)
        self.b_stop.setVisible(False)
        self.p_state.setText("To'xtagan" if err is None else "Xato")
        if err is not None:
            self.log.appendPlainText("XATO: %s" % err)
            QMessageBox.warning(self, "Jonli savdo", str(err))
        self.win.changed()

    def refresh(self) -> None:
        pol = self.db.latest_policy()
        if pol:
            self.kv["Siyosat"].set("v%d" % pol["version"])
            self.kv["Darvoza"].set("O'TDI" if pol["deployed"] else "O'TMADI", "up" if pol["deployed"] else "down")
        else:
            self.kv["Siyosat"].set("yo'q")
            self.kv["Darvoza"].set("—")
