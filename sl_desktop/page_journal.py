"""O'rganish jurnali: barcha o'rganish sikllari (state/learn_log.jsonl) — grafik va jadval."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from . import data as D
from . import widgets as W
from .charts import LearnHistoryChart


class JournalPage(W.Page):
    def __init__(self, app):
        super().__init__("O'rganish jurnali", "Har bir o'rganish sikli natijasi: tegilmagan davrdagi kutilma va darvoza qarori")
        self.app = app
        self.k_runs = W.KpiTile("Jami sikllar")
        self.k_pass = W.KpiTile("Darvozadan o'tgan")
        self.k_best = W.KpiTile("Eng yaxshi holdout")
        self.k_last = W.KpiTile("Oxirgi sikl")
        self.lay.addLayout(W.grid([self.k_runs, self.k_pass, self.k_best, self.k_last], 4))

        cc = W.Card("Holdout natijalari", "To'liq doira — darvozadan o'tgan, bo'sh doira — o'tmagan. Rang — rejim")
        self.legend = W.Legend()
        cc.body.addWidget(self.legend)
        self.chart = LearnHistoryChart(2.8)
        cc.body.addWidget(self.chart)
        self.lay.addWidget(cc)

        tc = W.Card("Jadval", "Qatorni tanlang — sabablar va strategiya pastda ko'rinadi")
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Vaqt", "Rejim", "Qaror", "Holdout R", "Bitim", "t", "Train R", "Vaqt, s"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(260)
        self.table.itemSelectionChanged.connect(self._select)
        tc.body.addWidget(self.table)
        self.detail = W.label("", "text2", wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tc.body.addWidget(self.detail)
        self.lay.addWidget(tc)
        self.lay.addStretch(1)
        self.rows = []

    def refresh(self) -> None:
        rows = D.learn_log(self.app.settings.state_dir())
        key = (len(rows), rows[-1].get("time") if rows else None)
        if not self.chart.need(key):
            return
        self.rows = rows
        n = len(rows)
        passed = sum(1 for r in rows if r.get("passed"))
        tests = [r["segments"]["test"]["exp"] for r in rows if (r.get("segments") or {}).get("test")]
        self.k_runs.set(str(n), "barcha rejimlar")
        self.k_pass.set("%d" % passed, ("%.0f%% sikllar" % (passed / n * 100)) if n else "")
        self.k_best.set(D.fmt_r(max(tests), 3) if tests else "—", "kutilma, bitta bitimga")
        if rows:
            last = rows[-1]
            self.k_last.set("✓ o'tdi" if last.get("passed") else "✕ o'tmadi", "%s · %s" % (last.get("mode"), last.get("time", "")[:16]),
                            "good" if last.get("passed") else "critical")
        else:
            self.k_last.set("—", "")
        self.legend.set(self.chart.show(rows, float(self.app.settings.get("SL_MIN_EXP_R"))))
        self.table.setRowCount(n)
        for i, r in enumerate(reversed(rows)):
            te = (r.get("segments") or {}).get("test") or {}
            tr = (r.get("segments") or {}).get("train") or {}
            vals = [r.get("time", ""), r.get("mode", ""), "✓ o'tdi" if r.get("passed") else "✕ o'tmadi",
                    D.fmt_r(te["exp"], 3) if te else "—", str(te.get("n", "—")), ("%.2f" % te["t"]) if te else "—",
                    D.fmt_r(tr["exp"], 3) if tr else "—", "%.0f" % r.get("seconds", 0)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, c, it)

    def _select(self) -> None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return
        d = self.rows[len(self.rows) - 1 - r]
        esc = html.escape
        txt = "<b>%s · %s</b><br>%s" % (esc(d.get("mode", "")), esc(d.get("time", "")), "<br>".join(
            ["Sabablar: " + esc("; ".join(d.get("reasons") or ["—"]))] +
            ["Strategiya:<br>&nbsp;&nbsp;" + esc(d.get("strategy") or "—").replace("\n", "<br>&nbsp;&nbsp;")]))
        self.detail.setText(txt)
