"""Bosh sahifa: robot holati bir qarashda — jarayon zanjiri, asosiy raqamlar, xavf o'lchagichlari."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QHBoxLayout, QPushButton

from . import data as D
from . import widgets as W
from .charts import EquityChart
from .settings import MODES


class DashboardPage(W.Page):
    def __init__(self, app):
        super().__init__("Bosh sahifa", "Robot nima qilyapti, oxirgi o'rganish natijasi va xavf ko'rsatkichlari bir qarashda")
        self.app = app
        self.pill = W.StatusPill("To'xtatilgan", "idle", big=True)
        self.head_right.addWidget(self.pill)

        self.banner = W.Banner()
        self.lay.addWidget(self.banner)

        pc = W.Card("Ish jarayoni", "Robot har doim shu ketma-ketlikda ishlaydi: savdo faqat tekshiruvdan o'tgan strategiya bilan")
        self.pipe = W.Pipeline()
        pc.body.addWidget(self.pipe)
        self.lay.addWidget(pc)

        self.k_bal = W.KpiTile("Balans")
        self.k_eq = W.KpiTile("Equity")
        self.k_pos = W.KpiTile("Ochiq pozitsiyalar")
        self.k_learn = W.KpiTile("Oxirgi o'rganish")
        self.lay.addLayout(W.grid([self.k_bal, self.k_eq, self.k_pos, self.k_learn], 4))

        row = QHBoxLayout()
        row.setSpacing(12)
        gc = W.Card("Xavf o'lchagichlari", "Chegaraga qanchalik yaqin: yashil — xavfsiz, sariq — ehtiyot, qizil — chegara yaqin")
        g = QHBoxLayout()
        self.g_kill = W.Gauge("Kill-switch")
        self.g_day = W.Gauge("Kunlik zarar")
        self.g_spread = W.Gauge("Spred")
        for x in (self.g_kill, self.g_day, self.g_spread):
            g.addWidget(x)
        gc.body.addLayout(g)
        row.addWidget(gc, 3)

        ac = W.Card("Tezkor amallar")
        self.b_learn = QPushButton("🧠  O'rganishni boshlash")
        self.b_learn.setObjectName("primary")
        self.b_learn.clicked.connect(lambda: app.go("learn"))
        self.b_live = QPushButton("💹  Jonli savdo paneli")
        self.b_live.clicked.connect(lambda: app.go("live"))
        self.b_res = QPushButton("📊  Natijalarni ko'rish")
        self.b_res.clicked.connect(lambda: app.go("results"))
        for b in (self.b_learn, self.b_live, self.b_res):
            ac.body.addWidget(b)
        ac.body.addStretch(1)
        row.addWidget(ac, 1)
        self.lay.addLayout(row)

        ec = W.Card("Oxirgi strategiya: kapital egri chizig'i", "Har bitimdan keyingi jami natija (R — bitta bitim xavfi birligida)")
        self.legend = W.Legend()
        ec.body.addWidget(self.legend)
        self.eq = EquityChart(2.6)
        ec.body.addWidget(self.eq)
        self.lay.addWidget(ec)
        self.lay.addStretch(1)

    def refresh(self) -> None:
        app = self.app
        st, fresh = D.live_status(app.settings.state_dir())
        live_on = app.live.running
        rep = D.latest_report(app.settings.state_dir())
        hist_ok = bool(D.history_preview(app.settings.resolve(app.settings.get("SL_HISTORY"))) is not None)

        # holat belgisi
        text, tone = app.robot_state(st if live_on and fresh else None)
        self.pill.set(text, tone)

        # zanjir
        learning = app.learn.running or bool(st and live_on and st.get("learning"))
        s_hist = "done" if hist_ok or (st and live_on) else "todo"
        s_learn = "active" if learning else ("done" if rep else "todo")
        if rep is None:
            s_gate = "todo"
        else:
            s_gate = "done" if rep.get("passed") else "fail"
        s_trade = "active" if live_on and st and st.get("ready") and (st.get("validated") or not st.get("require_pass")) \
            and not st.get("paused") else ("warn" if live_on else "todo")
        notes = [
            "fayl tayyor" if hist_ok else "tarix fayli tanlanmagan",
            "davom etmoqda…" if learning else (MODES[rep["mode"]][0] + " · " + rep.get("time", "")[5:16] if rep else "hali o'rganilmagan"),
            ("o'tdi ✓" if rep and rep.get("passed") else "o'tmadi — savdo yo'q") if rep else "—",
            "ishlamoqda" if s_trade == "active" else ("robot yoqilgan, savdo kutilmoqda" if live_on else "o'chirilgan"),
        ]
        self.pipe.set([s_hist, s_learn, s_gate, s_trade], notes)

        if rep and not rep.get("passed"):
            self.banner.set("Oxirgi strategiya qabul darvozasidan o'tmadi, shuning uchun robot u bilan savdo qilmaydi. "
                            "Sabab: " + html.escape("; ".join(rep.get("reasons", [])[:2])), "warning")
        elif st and live_on and not fresh:
            self.banner.set("Robot jarayoni yoqilgan, lekin 30 soniyadan beri holat yangilanmadi — MT5 terminalini tekshiring.",
                            "serious")
        else:
            self.banner.set("")

        # KPI
        cur = (st or {}).get("currency", "")
        if st and live_on:
            self.k_bal.set(D.fmt_money(st.get("balance", 0), cur), "%s · login %s" % (st.get("server", ""), st.get("login", "")))
            de = st.get("equity", 0) - st.get("day_equity", 0) if st.get("day_equity") else 0.0
            self.k_eq.set(D.fmt_money(st.get("equity", 0), cur), "bugun %s" % D.fmt_money(de, cur),
                          "good" if de > 0 else "critical" if de < 0 else None)
            pos = st.get("positions", [])
            pl = sum(x.get("profit", 0) for x in pos)
            self.k_pos.set(str(len(pos)), ("suzuvchi natija %s" % D.fmt_money(pl, cur)) if pos else "pozitsiya yo'q")
        else:
            for k in (self.k_bal, self.k_eq):
                k.set("—", "jonli robot ishlamayapti")
            self.k_pos.set("—", "")
        if rep:
            te = (rep.get("segments") or {}).get("test")
            self.k_learn.set(D.fmt_r(te["exp"], 3) if te else "—",
                             ("holdout kutilma · " + ("o'tdi" if rep.get("passed") else "o'tmadi")) if te else
                             "holdout natijasi yo'q", "good" if rep.get("passed") else "critical")
        else:
            self.k_learn.set("—", "hali o'rganilmagan")

        # o'lchagichlar
        self._gauges(st if live_on else None, app)
        if self.eq.need(((rep or {}).get("time"), (rep or {}).get("mode"))):
            self.legend.set(self.eq.show(rep))

    def _gauges(self, st, app) -> None:
        s = app.settings
        win, lim = int(s.get("SL_KILL_WINDOW")), float(s.get("SL_KILL_SUM_R"))
        if st:
            rs = st.get("rs", [])[-win:]
            tot = sum(rs)
            self.g_kill.set(max(0.0, -tot) / max(1e-9, -lim), "%+.1fR" % tot, "oxirgi %d bitim · chegara %.0fR" % (len(rs), lim))
            de, d0 = st.get("equity", 0), st.get("day_equity", 0)
            lossp = max(0.0, (d0 - de) / d0 * 100) if d0 else 0.0
            dl = float(st.get("max_daily_loss_pct", s.get("SL_MAX_DAILY_LOSS_PCT")))
            self.g_day.set(lossp / dl, "%.2f%%" % lossp, "limit %.1f%%" % dl)
            sp, ms = st.get("spread", 0), st.get("max_spread", s.get("SL_MAX_SPREAD"))
            self.g_spread.set(sp / ms if ms else 0, "%.2f" % sp, "maks. %.2f" % ms)
        else:
            self.g_kill.set(0, "—", "chegara %.0fR" % lim)
            self.g_day.set(0, "—", "limit %.1f%%" % float(s.get("SL_MAX_DAILY_LOSS_PCT")))
            self.g_spread.set(0, "—", "maks. %.2f" % float(s.get("SL_MAX_SPREAD")))
