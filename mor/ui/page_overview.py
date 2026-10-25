from __future__ import annotations

import time

from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from . import theme as T
from . import widgets as W
from .page import Page, ago, fdate


class OverviewPage(Page):
    key, title = "overview", "Umumiy ko'rinish"

    def __init__(self, win):
        super().__init__(win)
        self.p_conn = W.pill("MT5 ulanmagan")
        self.p_sym = W.pill("")
        self.btn_train = W.button("O'rgatishga o'tish", "primary", on=lambda: win.go("training"))
        self.root.addWidget(W.page_header(self.title, [self.p_conn, self.p_sym], [self.btn_train]))
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(16)
        self.root.addWidget(body, 1)
        k = QGridLayout()
        k.setSpacing(16)
        self.k_bal = W.Kpi("Balans (DEMO)", "—", "MT5 ulanmagan")
        self.k_test = W.Kpi("Test natijasi (OOS)", "—", "siyosat hali o'qitilmagan")
        self.k_mem = W.Kpi("Xotiradagi tajriba", "0", "bitim")
        self.k_pol = W.Kpi("Agent siyosati", "—", "")
        for i, w in enumerate((self.k_bal, self.k_test, self.k_mem, self.k_pol)):
            k.addWidget(w, 0, i)
        v.addLayout(k)
        mid = QGridLayout()
        mid.setSpacing(16)
        mid.setColumnStretch(0, 2)
        mid.setColumnStretch(1, 1)
        self.chart = W.LineChart(210)
        self.chart.empty_text = "Test bitimlari hali yo'q — avval agentni o'rgating"
        c1 = W.Card("Test davri: jamlangan natija (R)")
        c1.add(self.chart, 1)
        mid.addWidget(c1, 0, 0)
        c2 = W.Card("Agent holati")
        self.kv = {n: W.KV(n) for n in ("Holat", "Siyosat", "Darvoza", "Qonuniyatlar", "Oxirgi o'rganish", "Ma'lumotlar")}
        for w in self.kv.values():
            c2.add(w)
        mid.addWidget(c2, 0, 1)
        v.addLayout(mid)
        self.table = W.Table(["Vaqt (UTC)", "Instrument", "Yo'nalish", "Kirish", "Chiqish", "Natija (R)", "Sabab", "Davr"],
                             mono_cols=(0, 3, 4, 5), stretch_col=6)
        c3 = W.Card("So'nggi bitimlar")
        c3.add(self.table, 1)
        v.addWidget(c3, 1)

    def refresh(self) -> None:
        db = self.db
        pol = db.latest_policy()
        st = db.experience_stats()
        ds = db.datasets()
        self.k_mem.set("{:,}".format(st["n"]).replace(",", " "), "bitim · %d instrument" % st["symbols"])
        self.p_sym.setText(self.settings["symbol"] + " · " + self.settings["tf"])
        live = self.win.live_status
        if live.get("connected"):
            self.p_conn.setText("MT5 ulangan · DEMO")
            self.k_bal.set("%.2f" % live.get("balance", 0), "%s · equity %.2f" % (live.get("currency", ""), live.get("equity", 0)))
        else:
            self.p_conn.setText("MT5 ulanmagan")
            self.k_bal.set("—", "Jonli savdo sahifasidan ulaning")
        if pol:
            m = pol["metrics"]
            tg = m.get("test_guard") if m.get("guard_rules") else m.get("test")
            tg = tg or {}
            tone = "up" if tg.get("exp", 0) > 0 else "down"
            self.k_test.set("%+.3f R" % tg.get("exp", 0), "%d bitim · t = %.2f" % (tg.get("n", 0), tg.get("t", 0)), tone)
            ok = pol["deployed"]
            self.k_pol.set("v %d" % pol["version"], "darvozadan o'tdi" if ok else "darvozadan o'tmadi")
            self.kv["Siyosat"].set("v%d" % pol["version"])
            self.kv["Darvoza"].set("O'TDI" if ok else "O'TMADI", "up" if ok else "down")
            self.kv["Oxirgi o'rganish"].set(ago(pol["created"]))
        else:
            self.k_test.set("—", "siyosat hali o'qitilmagan")
            self.k_pol.set("—", "")
            self.kv["Siyosat"].set("yo'q")
            self.kv["Darvoza"].set("—")
            self.kv["Oxirgi o'rganish"].set("hech qachon")
        ver = len(db.lessons("verified"))
        self.kv["Qonuniyatlar"].set("%d ta tasdiqlangan" % ver)
        self.kv["Ma'lumotlar"].set("%d dataset" % len(ds))
        busy = self.win.train_job is not None
        self.kv["Holat"].set("O'rganmoqda" if busy else ("Jonli savdoda" if live.get("running") else "Kutmoqda"),
                             "accent" if busy else ("up" if live.get("running") else ""))
        # grafik: test bitimlari bo'yicha jamlangan R
        rows = db.experiences(split="test", limit=20000, order="ts_close DESC")[::-1]
        rows.sort(key=lambda r: r["ts_close"])
        if rows:
            acc, cum = 0.0, []
            for r in rows:
                acc += r["r"]
                cum.append(acc)
            step = max(1, len(cum) // 400)
            idx = list(range(0, len(cum), step))
            self.chart.set_series([{"name": "Jami R", "color": T.ACCENT, "values": [cum[i] for i in idx]}],
                                  [fdate(rows[i]["ts_close"], True) for i in idx])
        else:
            self.chart.set_series([])
        last = db.experiences(limit=6)
        self.table.fill([[fdate(r["ts_close"]), r["symbol"], "BUY" if r["side"] > 0 else "SELL", "%.5g" % r["entry"],
                          "%.5g" % r["exit"], ("%+.2f" % r["r"], "up" if r["r"] > 0 else "down"), r["reason"],
                          {"train": "o'rganish", "val": "tasdiq", "val_explore": "tasdiq.", "test": "test", "live": "jonli"}.get(r["split"], r["split"])]
                         for r in last], [15, 11, 9, 11, 11, 10, 13, 10])
