"""Natijalar sahifasi: oxirgi o'rganish hisoboti — xulosa, darvoza shartlari, egri chiziq, oylik natija, strategiya."""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Optional

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from . import data as D
from . import theme
from . import widgets as W
from .charts import EquityChart, MonthlyChart, SegmentBars
from .settings import MODES

FEATURES = {
    "rsi14": "RSI(14)", "rsi5": "RSI(5)", "ema20_dist": "EMA20 dan masofa", "ema50_dist": "EMA50 dan masofa",
    "ema200_dist": "EMA200 dan masofa", "ema10_dist": "EMA10 dan masofa", "ema100_dist": "EMA100 dan masofa",
    "ema20_slope": "EMA20 qiyaligi", "ema50_slope": "EMA50 qiyaligi", "ema20_50": "EMA20−EMA50", "bb_z": "Bollinger z",
    "bb_z20": "Bollinger z(20)", "bb_z50": "Bollinger z(50)", "atr_ratio": "Volatillik nisbati (ATR14/ATR100)",
    "roc3": "3 shamlik o'zgarish", "roc12": "12 shamlik o'zgarish", "roc48": "48 shamlik o'zgarish", "body": "Sham tanasi",
    "range": "Sham diapazoni", "upper_wick": "Yuqori soya", "lower_wick": "Pastki soya", "don_pos20": "Donchian(20) ichidagi o'rin",
    "brk_hi20": "20 shamlik maksimum yorilishi", "brk_lo20": "20 shamlik minimum yorilishi", "stoch14": "Stoxastik(14)",
    "vol_ratio": "Hajm nisbati", "hour": "Soat (UTC)", "dow": "Hafta kuni", "atr_pts": "ATR (‰ narxdan)",
    "hour_sin": "Soat (sin)", "hour_cos": "Soat (cos)",
}
FAMILY = {"trend_pullback": "Trend ichida orqaga qaytish", "donchian": "Donchian kanali yorilishi",
          "bb_revert": "Bollinger z-score qaytish"}


def explain(rep: Dict[str, Any]) -> str:
    """Natijani oddiy tilda tushuntirish."""
    te = (rep.get("segments") or {}).get("test")
    tr = (rep.get("segments") or {}).get("train")
    if rep.get("passed"):
        return ("Strategiya o'rganishda ishtirok etmagan eng yangi davrda ham foydali chiqdi: %d bitimda o'rtacha %+.3fR "
                "(har bitimda xavf qilingan summaning %.0f%%i). Shuning uchun u jonli (DEMO) savdoga qo'yildi. "
                "Baribir 1–2 oy kichik riskda kuzatib boring." % (te["n"], te["exp"], te["exp"] * 100))
    failed = [c["label"].lower() for c in rep.get("checks") or [] if not c.get("ok")]
    if te and te.get("exp", 0) > 0 and (not tr or te["exp"] >= tr.get("exp", 0) * 0.5) and failed:
        return ("Tegilmagan davrda natija musbat (%+.3fR, %d bitim), lekin shart bajarilmadi: %s. Bunday natija tasodif "
                "bo'lishi mumkin, shuning uchun robot ehtiyotkorlik bilan savdo qilmaydi. Ko'proq tarix yoki boshqa rejim "
                "bilan sinab ko'ring." % (te["exp"], te["n"], ", ".join(failed)))
    if te and tr:
        return ("O'rganish davrida natija %+.3fR edi, lekin tegilmagan davrda %+.3fR. Bu — tarixga \"yodlab olish\" "
                "(overfitting) belgisi: topilgan qonuniyat yangi ma'lumotda takrorlanmadi. Robot bunday strategiya bilan "
                "savdo qilmaydi — himoya to'g'ri ishladi." % (tr["exp"], te["exp"]))
    return "Validatsiyadan o'tgan strategiya topilmadi: " + "; ".join(rep.get("reasons", [])[:2])


class ResultsPage(W.Page):
    def __init__(self, app):
        super().__init__("Natijalar", "Oxirgi o'rganish hisoboti: strategiya tegilmagan davrda qanday natija berdi")
        self.app = app
        self.mode = QComboBox()
        self.mode.addItem("Eng oxirgisi", "")
        for k, (t, ic, _d) in MODES.items():
            self.mode.addItem("%s  %s" % (ic, t), k)
        self.mode.currentIndexChanged.connect(lambda *_: self.refresh())
        self.head_right.addWidget(self.mode)

        self.empty = W.Banner("Hali hisobot yo'q. «O'rganish» sahifasida o'rganishni ishga tushiring.", "info")
        self.lay.addWidget(self.empty)

        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(16)
        self.lay.addWidget(self.content)

        # xulosa
        hero = W.Card()
        hr = QHBoxLayout()
        self.verdict = W.StatusPill("", "idle", big=True)
        hr.addWidget(self.verdict)
        hr.addStretch(1)
        self.meta = W.label("", "muted")
        hr.addWidget(self.meta)
        hero.body.addLayout(hr)
        self.expl = W.label("", "text2", wrap=True, plain=True)
        hero.body.addWidget(self.expl)
        cl.addWidget(hero)

        self.k = {k: W.KpiTile(t) for k, t in (("exp", "Holdout kutilma"), ("win", "Yutuq ulushi"), ("pf", "Profit faktor"),
                                                ("t", "Ishonch (t)"), ("dd", "Maks. pasayish"), ("n", "Bitimlar"))}
        cl.addLayout(W.grid(list(self.k.values()), 6))

        row = QHBoxLayout()
        row.setSpacing(12)
        gc = W.Card("Qabul darvozasi", "Savdoga qo'yish uchun HAMMA shart bajarilishi kerak. Sichqonchani ustiga olib boring — izoh")
        self.gate = W.GateList()
        gc.body.addWidget(self.gate)
        self.reasons = W.label("", "muted", wrap=True, plain=True)
        gc.body.addWidget(self.reasons)
        row.addWidget(gc, 1)
        sc_ = W.Card("Davrlar bo'yicha o'rtacha natija", "O'rganish davridagi yaxshi natija tegilmagan davrda saqlanishi kerak")
        self.bars = SegmentBars(2.6)
        sc_.body.addWidget(self.bars)
        row.addWidget(sc_, 1)
        cl.addLayout(row)

        ec = W.Card("Kapital egri chizig'i", "Har bitimdan keyingi jami natija (R). Fon ranglari — davrlar")
        self.legend = W.Legend()
        ec.body.addWidget(self.legend)
        self.eq = EquityChart(3.0)
        ec.body.addWidget(self.eq)
        cl.addWidget(ec)

        mc = W.Card("Oylik natija", "Har oy yig'indisi: ko'k — foyda, qizil — zarar")
        mc.body.addWidget(W.Legend([("foydali oy", theme.c("pos")), ("zararli oy", theme.c("neg"))]))
        self.month = MonthlyChart(2.4)
        mc.body.addWidget(self.month)
        cl.addWidget(mc)

        self.strat = W.Card("Strategiya", "Robot topgan qoidalar oddiy tilda")
        self.strat_box = QVBoxLayout()
        self.strat.body.addLayout(self.strat_box)
        cl.addWidget(self.strat)

        self.extra = W.Card("Qo'shimcha tafsilotlar")
        self.extra_box = QVBoxLayout()
        self.extra.body.addLayout(self.extra_box)
        cl.addWidget(self.extra)
        self.lay.addStretch(1)

    def select_mode(self, mode: str) -> None:
        i = self.mode.findData(mode)
        if i >= 0:
            self.mode.setCurrentIndex(i)
        self.refresh()

    def refresh(self) -> None:
        rep = D.latest_report(self.app.settings.state_dir(), self.mode.currentData() or None)
        self.empty.setVisible(rep is None)
        self.content.setVisible(rep is not None)
        if rep is None:
            return
        ok = bool(rep.get("passed"))
        self.verdict.set("Darvozadan O'TDI — savdoga tayyor" if ok else "Darvozadan O'TMADI — savdo qilinmaydi",
                         "good" if ok else "critical")
        t, ic, _ = MODES.get(rep.get("mode"), ("?", "", ""))
        self.meta.setText("%s %s · %s %s · %s · %.0f s · %s baho%s" % (
            ic, t, rep.get("symbol", ""), rep.get("tf", ""), rep.get("time", ""), rep.get("seconds", 0), rep.get("evals", 0),
            (" · urinish " + rep["extra"]["attempt"]) if "attempt" in (rep.get("extra") or {}) else ""))
        self.expl.setText(explain(rep))

        te = (rep.get("segments") or {}).get("test") or {}
        tr = (rep.get("segments") or {}).get("train") or {}
        if te:
            d = te.get("exp", 0) - tr.get("exp", 0) if tr else None
            self.k["exp"].set(D.fmt_r(te.get("exp", 0), 3), ("train %s" % D.fmt_r(tr.get("exp", 0), 3)) if tr else "",
                              "critical" if d is not None and d < 0 else "good" if d is not None else None)
            self.k["win"].set("%.0f%%" % (te.get("win", 0) * 100), "holdout bitimlarining foydalisi")
            self.k["pf"].set("%.2f" % te.get("pf", 0), "foyda / zarar · ≥ 1.0 foydali")
            self.k["t"].set("%.2f" % te.get("t", 0), "≥ 2 — kuchli, < 1 — tasodif bo'lishi mumkin")
            self.k["dd"].set("%.1fR" % te.get("dd", 0), "eng chuqur ketma-ket pasayish")
            self.k["n"].set(str(te.get("n", 0)), "holdout davrida")
        else:
            for k in self.k.values():
                k.set("—", "holdout natijasi yo'q")
        self.gate.set(rep.get("checks") or [])
        self.reasons.setText(("Sabablar: " + "; ".join(rep.get("reasons", []))) if rep.get("reasons") else "")
        self.bars.show(rep, float(self.app.settings.get("SL_MIN_EXP_R")))
        self.legend.set(self.eq.show(rep))
        self.month.show(rep)
        self._strategy(rep)
        self._extra(rep)

    # ------------------------------------------------------------ strategiya
    def _strategy(self, rep: Dict[str, Any]) -> None:
        W.clear_layout(self.strat_box)
        text = rep.get("strategy") or ""
        if not text:
            self.strat_box.addWidget(W.label("Strategiya shakllanmadi.", "muted"))
            return
        mode = rep.get("mode")
        if mode == "genetic":
            for i, ln in enumerate(text.splitlines(), 1):
                self.strat_box.addWidget(self._rule(i, ln))
        elif mode == "optimizer":
            m = re.match(r"(\w+)\s+(\{.*\})", text)
            if m:
                import json
                fam, params = m.group(1), json.loads(m.group(2))
                self.strat_box.addWidget(W.label("<b>%s</b> (%s)" % (FAMILY.get(fam, fam), fam)))
                g = QGridLayout()
                for i, (k, v) in enumerate(params.items()):
                    g.addWidget(W.label(k, "muted"), i // 4, (i % 4) * 2)
                    g.addWidget(W.label("<b>%s</b>" % v), i // 4, (i % 4) * 2 + 1)
                self.strat_box.addLayout(g)
            else:
                self.strat_box.addWidget(W.label(text, wrap=True, plain=True))
        else:
            self.strat_box.addWidget(W.label(text, wrap=True, plain=True))
            feats = (rep.get("extra") or {}).get("top_features") or []
            if feats:
                self.strat_box.addWidget(W.label("Eng muhim xususiyatlar: " + ", ".join(FEATURES.get(f, f) for f in feats),
                                                 "text2", wrap=True))

    def _rule(self, i: int, ln: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        m = re.match(r"(BUY|SELL):\s*(.*?)\s*\|\s*(.*)", ln)
        if not m:
            lay.addWidget(W.label(ln, wrap=True, plain=True))
            return w
        side, conds, risk = m.groups()
        lay.addWidget(W.label("Qoida %d" % i, "muted"))
        pill = W.StatusPill("SOTIB OLISH" if side == "BUY" else "SOTISH", "info" if side == "BUY" else "serious")
        lay.addWidget(pill)
        parts = []
        for cnd in conds.split(" VA "):
            cm = re.match(r"(\S+)\s*([<>])\s*(\S+)", cnd.strip())
            parts.append("<b>%s</b> %s %s" % (FEATURES.get(cm.group(1), cm.group(1)), html.escape(cm.group(2)), cm.group(3))
                         if cm else html.escape(cnd))
        lay.addWidget(W.label("agar " + "  <i>va</i>  ".join(parts), wrap=True), 1)
        lay.addWidget(W.label(risk.replace("ushlash", "maks.").replace("sham", "sham"), "text2"))
        return w

    def _extra(self, rep: Dict[str, Any]) -> None:
        W.clear_layout(self.extra_box)
        ex = rep.get("extra") or {}
        rows = []
        if "oos_by_family" in ex:
            for k, v in ex["oos_by_family"].items():
                rows.append("%s %s: OOS %+.3fR, %d bitim, t=%.2f, foydali oynalar %.0f%%" % (
                    "★" if k == ex.get("best_family") else "·", FAMILY.get(k, k), v["exp"], v["n"], v["t"], v["pos_windows"] * 100))
        if "generations" in ex:
            rows.append("Avlodlar: %s · nomzodlar: %s · validatsiyadan o'tgan: %s · eng yaxshi train t: %s" % (
                ex.get("generations"), ex.get("candidates"), ex.get("val_passed"), ex.get("best_train_t")))
        if "model" in ex:
            rows.append("Model: %s" % ex["model"])
        for k, v in (ex.get("confirm") or {}).items():
            rows.append("%s Tasdiq · %s: %+.3fR, %d bitim, t=%.2f" % ("✓" if v.get("ok") else "✕", k, v["exp"], v["n"], v["t"]))
        costs = rep.get("costs") or {}
        if costs:
            rows.append("Simulyatsiya xarajatlari: spred %.2f, sirpanish %.2f (har bitimda)" % (costs.get("spread", 0),
                                                                                              costs.get("slippage", 0)))
        if rep.get("history"):
            rows.append("Tarix: %s → %s, %s sham" % (rep["history"][0][:10], rep["history"][1][:10], rep.get("bars", "")))
        for r in rows:
            self.extra_box.addWidget(W.label(r, "text2", wrap=True, plain=True))
        self.extra.setVisible(bool(rows))
