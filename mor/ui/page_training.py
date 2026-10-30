from __future__ import annotations

import time
from typing import Any, Dict, List

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from . import theme as T
from . import widgets as W
from .page import Page


class TrainingPage(Page):
    key, title = "training", "Agentni o'rgatish"

    def __init__(self, win):
        super().__init__(win)
        self.p_state = W.pill("Kutmoqda")
        self.b_settings = W.button("Sozlamalar", on=lambda: win.go("settings"))
        self.b_start = W.button("O'rgatishni boshlash", "primary", on=self.start)
        self.b_stop = W.button("To'xtatish", "danger", on=self.stop)
        self.b_stop.setVisible(False)
        self.root.addWidget(W.page_header(self.title, [self.p_state], [self.b_settings, self.b_stop, self.b_start]))
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(16)
        self.root.addWidget(body, 1)
        k = QGridLayout()
        k.setSpacing(16)
        self.kp = [W.Kpi("Tadqiqot bitimlari: o'rtacha R", "—", "oxirgi epoxa"), W.Kpi("Foydali bitimlar (val)", "—", ""),
                   W.Kpi("Tasdiqlash (val), R", "—", "o'rganilmagan davr"), W.Kpi("Tadqiqot (ε)", "—", ""),
                   W.Kpi("Tezlik", "—", "qadam / soniya")]
        for i, w in enumerate(self.kp):
            k.addWidget(w, 0, i)
        v.addLayout(k)
        mid = QGridLayout()
        mid.setSpacing(16)
        mid.setColumnStretch(0, 2)
        mid.setColumnStretch(1, 1)
        v.addLayout(mid, 1)
        self.chart = W.LineChart(230)
        self.chart.empty_text = "Tasdiqlash natijalari o'qitish davomida shu yerda paydo bo'ladi"
        c1 = W.Card("Natija dinamikasi (bitimga o'rtacha R)", W.Legend([("O'rganish davri", T.ACCENT), ("Tasdiqlash davri (val)", T.WARN)]))
        c1.add(self.chart, 1)
        self.log = W.log_view(110)
        c1.add(self.log)
        mid.addWidget(c1, 0, 0)
        right = QVBoxLayout()
        right.setSpacing(16)
        c2 = W.Card("Jarayon")
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(16, 14, 16, 4)
        pl.addWidget(self.prog)
        c2.add(pw)
        self.kv_ep = W.KV("Epoxa", "—")
        self.kv_eta = W.KV("Tugashiga", "—")
        self.kv_mem = W.KV("Xotira (oddiy/namuna/xato)", "—")
        for w in (self.kv_ep, self.kv_eta, self.kv_mem):
            c2.add(w)
        right.addWidget(c2)
        c3 = W.Card("Giperparametrlar")
        self.hp = {n: W.KV(n) for n in ("Algoritm", "O'rganish tezligi", "Diskont (γ)", "Tajriba xotirasi", "Stop-loss", "Datasetlar")}
        for w in self.hp.values():
            c3.add(w)
        right.addWidget(c3)
        self.b_sig = W.button("Tekshirish", on=self.check_signal)
        c4 = W.Card("Signal tekshiruvi", self.b_sig)
        self.sig_table = W.Table(["Instr.", "Xarajat", "Val", "Test", "Xulosa"], mono_cols=(1, 2, 3))
        self.sig_table.setFixedHeight(36 * 4 + 34)
        c4.add(self.sig_table)
        self.sig_note = W.label("O'qitishdan oldin: ma'lumotda kelajak narxni bashorat qiladigan narsa bormi? "
                                "Korrelyatsiya ~0 bo'lsa, o'qitish foyda bermaydi.", "muted", wrap=True)
        self.sig_note.setContentsMargins(16, 10, 16, 12)
        c4.add(self.sig_note)
        right.addWidget(c4)
        right.addStretch(1)
        mid.addLayout(right, 0, 1)
        self.t0 = 0.0
        self.val_series: List[Any] = []
        self.tr_series: List[Any] = []

    # ------------------------------------------------------------ signal tekshiruvi
    def check_signal(self) -> None:
        if getattr(self, "sig_job", None) is not None:
            return
        from .. import paths, signal as sg
        from ..db import Database
        from ..trainer import load_series
        from .workers import Job
        cfg = self.settings.train_cfg()
        db_file = str(paths.db_path())

        def work(emit, stopped):
            db = Database(db_file)
            try:
                rows = sg.check_all(load_series(db, cfg))
                return {"rows": rows, "advice": sg.advice(rows)}
            finally:
                db.close()
        self.sig_job = Job(work, self)
        self.sig_job.finished_with.connect(self._signal_done)
        self.b_sig.setEnabled(False)
        self.sig_note.setText("Tekshirilmoqda…")
        self.sig_job.start()

    def _signal_done(self, res, err) -> None:
        self.sig_job = None
        self.b_sig.setEnabled(True)
        if err is not None:
            self.sig_note.setText("Xato: %s" % err)
            return
        tone = {"bor": "up", "zaif": "warn", "yo'q": "down"}
        rows = [[r["symbol"], "%.3fR" % r["cost_r"], "%+.2f" % r["val_corr"], "%+.2f" % r["test_corr"],
                 (r["verdict"].capitalize(), tone[r["verdict"]])] for r in res["rows"]]
        self.sig_table.fill(rows, [10, 9, 8, 8, 9])
        self.sig_note.setText(res["advice"] + ("" if all(r["news"] for r in res["rows"]) or not res["rows"]
                                               else "  (Kalendar yuklanmagan — yangilik belgilari bo'sh.)"))

    # ------------------------------------------------------------ boshqaruv
    def start(self) -> None:
        self.val_series, self.tr_series = [], []
        self.chart.set_series([])
        self.log.clear()
        self.win.start_training()

    def stop(self) -> None:
        self.win.stop_training()
        self.b_stop.setEnabled(False)
        self.p_state.setText("To'xtatilmoqda…")

    def on_started(self, cfg) -> None:
        self.t0 = time.time()
        self.b_start.setVisible(False)
        self.b_stop.setVisible(True)
        self.b_stop.setEnabled(True)
        self.p_state.setText("O'rganmoqda · epoxa 0 / %d" % cfg.epochs)
        self.prog.setRange(0, cfg.epochs)
        self.prog.setValue(0)

    def on_event(self, e: Dict[str, Any]) -> None:
        t = e.get("type")
        if t == "log":
            self.log.appendPlainText(e["msg"])
        elif t == "epoch":
            ep, n = e["epoch"], e["epochs"]
            self.p_state.setText("O'rganmoqda · epoxa %d / %d" % (ep, n))
            self.prog.setValue(ep)
            self.kp[0].set("%+.3f R" % e["mean_r"], "%d bitim" % e["trades"], "up" if e["mean_r"] > 0 else "down")
            self.kp[3].set("%.2f" % e["eps"], "1.00 → 0.05")
            self.kp[4].set("{:,}".format(int(e["sps"])).replace(",", " "), "qadam / soniya")
            m = e["memory"]
            self.kv_mem.set("%d / %d / %d" % (m["normal"], m["elite"], m["mistake"]))
            self.kv_ep.set("%d / %d" % (ep, n))
            el = time.time() - self.t0
            self.kv_eta.set("≈ %d daq." % max(0, round(el / ep * (n - ep) / 60)) if ep else "—")
            if "val" in e:
                v, tr = e["val"], e["train_eval"]
                self.kp[1].set("%.1f %%" % (v["win"] * 100), "%d bitim" % v["n"])
                self.kp[2].set("%+.3f R" % v["exp"], "t = %.2f" % v["t"], "up" if v["exp"] > 0 else "down")
                self.val_series.append(v["exp"])
                self.tr_series.append(tr["exp"])
                self.chart.set_series([{"name": "O'rganish", "color": T.ACCENT, "values": self.tr_series},
                                       {"name": "Val", "color": T.WARN, "values": self.val_series}],
                                      ["epoxa %d" % (i * self.settings["eval_every"] + self.settings["eval_every"]) for i in range(len(self.val_series))])
                self.log.appendPlainText("epoxa %d · val %+.3fR (n=%d) · o'rganish %+.3fR" % (ep, v["exp"], v["n"], tr["exp"]))
        elif t == "done":
            m = e["metrics"]
            g = m["gate"]
            self.log.appendPlainText("Yakun: test %+.3fR (n=%d, t=%.2f) → darvoza %s" % (
                g["exp"], g["n"], g["t"], "O'TDI" if m["gate_ok"] else "o'tmadi"))

    def on_finished(self, res, err) -> None:
        self.b_start.setVisible(True)
        self.b_stop.setVisible(False)
        if err is not None:
            self.p_state.setText("Xato")
            self.log.appendPlainText("XATO: %s" % err)
        else:
            self.p_state.setText("Tugadi")
            self.prog.setValue(self.prog.maximum())

    def refresh(self) -> None:
        s = self.settings
        cfg = s.train_cfg()
        self.hp["Algoritm"].set("Double DQN")
        self.hp["O'rganish tezligi"].set("%g" % cfg.lr)
        self.hp["Diskont (γ)"].set("%g" % cfg.gamma)
        self.hp["Tajriba xotirasi"].set("{:,}".format(cfg.replay).replace(",", " "))
        self.hp["Stop-loss"].set("%g × ATR" % cfg.sl_atr)
        ds = [d for d in self.db.datasets() if d["tf"] == cfg.tf and (not cfg.symbols or d["symbol"] in cfg.symbols)]
        self.hp["Datasetlar"].set("%d ta (%s)" % (len(ds), cfg.tf))
