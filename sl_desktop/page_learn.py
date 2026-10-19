"""O'rganish sahifasi: 3 qadam — rejim, tarix, parametrlar — va jarayonni jonli kuzatish."""
from __future__ import annotations

import html

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QSlider, QSpinBox, QVBoxLayout)

from . import data as D
from . import widgets as W
from .charts import PriceSplitChart, ProgressChart
from .settings import MODES, app_dir


def human_secs(s: float) -> str:
    s = int(max(0, s))
    return "%d s" % s if s < 90 else "%d daq %02d s" % (s // 60, s % 60) if s < 3600 else "%d soat %02d daq" % (s // 3600, s % 3600 // 60)


class LearnPage(W.Page):
    def __init__(self, app):
        super().__init__("O'rganish", "Robot tarix ustida o'zi strategiya yaratadi va uni tegilmagan oxirgi davrda tekshiradi. "
                                      "Savdo qilinmaydi, MT5 kerak emas.")
        self.app = app
        s = app.settings

        # 1-qadam: rejim
        c1 = W.Card("1. Rejimni tanlang", "Uch xil usul — har biri strategiyani boshqacha \"ixtiro qiladi\"")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_cards = {}
        for k, (title, icon, desc) in MODES.items():
            mc = W.ModeCard(k, title, icon, desc)
            self.mode_group.addButton(mc)
            self.mode_cards[k] = mc
            row.addWidget(mc)
        c1.body.addLayout(row)
        self.lay.addWidget(c1)
        self.mode_cards.get(s.get("SL_MODE"), self.mode_cards["genetic"]).setChecked(True)
        self.mode_group.buttonToggled.connect(self._mode_changed)

        # 2-qadam: tarix
        c2 = W.Card("2. Tarix ma'lumoti", "Tarix vaqt bo'yicha 3 qismga bo'linadi: o'rganish 60% → validatsiya 20% → "
                                         "holdout 20% (eng yangi; qidiruvda umuman ishlatilmaydi)")
        fr = QHBoxLayout()
        self.hist = QLineEdit(s.get("SL_HISTORY"))
        self.hist.setPlaceholderText("data/XAUUSD_M15.csv")
        self.hist.editingFinished.connect(self._hist_changed)
        b = QPushButton("📁  Tanlash…")
        b.clicked.connect(self._browse)
        fr.addWidget(self.hist, 1)
        fr.addWidget(b)
        c2.body.addLayout(fr)
        self.hist_info = W.label("", "text2")
        c2.body.addWidget(self.hist_info)
        self.price = PriceSplitChart(2.4)
        c2.body.addWidget(self.price)
        self.lay.addWidget(c2)

        # 3-qadam: parametrlar
        c3 = W.Card("3. Parametrlar", "Ko'proq vaqt — chuqurroq qidiruv. Ko'p urinish — darvoza avtomatik qattiqlashadi")
        g = QHBoxLayout()
        g.setSpacing(24)
        col = QVBoxLayout()
        col.addWidget(W.label("O'rganish vaqti (har urinishga)", "text2"))
        self.budget = QSlider(Qt.Orientation.Horizontal)
        self.budget.setRange(1, 60)                    # x30 s
        self.budget.setValue(max(1, min(60, int(s.get("SL_BUDGET_SEC")) // 30)))
        self.budget_lbl = W.label("", "h2")
        self.budget.valueChanged.connect(self._budget_changed)
        col.addWidget(self.budget)
        col.addWidget(self.budget_lbl)
        g.addLayout(col, 2)
        col2 = QVBoxLayout()
        col2.addWidget(W.label("Urinishlar soni", "text2"))
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 20)
        self.repeat.setValue(int(s.get("SL_REPEAT")))
        self.repeat.valueChanged.connect(self._budget_changed)
        col2.addWidget(self.repeat)
        self.t_lbl = W.label("", "muted", wrap=True)
        col2.addWidget(self.t_lbl)
        g.addLayout(col2, 1)
        col3 = QVBoxLayout()
        col3.addWidget(W.label("Tasdiqlovchi instrumentlar (ixtiyoriy)", "text2"))
        self.confirm = QLineEdit(s.get("SL_CONFIRM"))
        self.confirm.setPlaceholderText("data/XAGUSD_M15.csv|0.03|0.01;data/EURUSD_M15.csv|0.00012")
        self.confirm.setToolTip("Strategiya boshqa instrumentlarda ham foydali bo'lishi kerak (kamida yarmida). "
                                "Format: fayl|spred|sirpanish; ...")
        col3.addWidget(self.confirm)
        self.force = QCheckBox("Darvozadan o'tmasa ham saqlash (faqat tadqiqot)")
        col3.addWidget(self.force)
        g.addLayout(col3, 2)
        c3.body.addLayout(g)
        self.lay.addWidget(c3)

        # ishga tushirish va jarayon
        c4 = W.Card("Jarayon")
        top = QHBoxLayout()
        self.start_btn = QPushButton("▶  O'rganishni boshlash")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("■  To'xtatish")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.clicked.connect(lambda: app.learn.stop())
        self.stop_btn.setEnabled(False)
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addSpacing(12)
        self.state_pill = W.StatusPill("Tayyor", "idle")
        top.addWidget(self.state_pill)
        top.addStretch(1)
        self.eta = W.label("", "text2")
        top.addWidget(self.eta)
        c4.body.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        c4.body.addWidget(self.bar)
        self.step_lbl = W.label("", "muted", wrap=True)
        c4.body.addWidget(self.step_lbl)
        self.banner = W.Banner()
        c4.body.addWidget(self.banner)
        self.pchart = ProgressChart(2.2)
        c4.body.addWidget(self.pchart)
        lh = QHBoxLayout()
        lh.addWidget(W.label("Jurnal", "h2"))
        lh.addStretch(1)
        self.log_toggle = QPushButton("Ko'rsatish")
        self.log_toggle.setObjectName("link")
        self.log_toggle.clicked.connect(lambda: self._toggle_log())
        lh.addWidget(self.log_toggle)
        c4.body.addLayout(lh)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(200)
        self.log.setVisible(False)
        c4.body.addWidget(self.log)
        self.lay.addWidget(c4)
        self.progress_card = c4
        self.lay.addStretch(1)

        app.learn.line.connect(self._on_line)
        app.learn.progress.connect(self._on_progress)
        app.learn.finished.connect(self._on_finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._reset_progress()
        self._budget_changed()
        self._hist_changed()

    # ------------------------------------------------------------ boshqaruv
    def mode(self) -> str:
        b = self.mode_group.checkedButton()
        return b.key if b else "genetic"

    def _mode_changed(self, *_a) -> None:
        self.app.settings.set("SL_MODE", self.mode())
        self.app.settings.save()

    def _browse(self) -> None:
        start = str(Path(self.app.settings.resolve(self.hist.text())).parent) if self.hist.text() else str(app_dir())
        f, _ = QFileDialog.getOpenFileName(self, "Tarix faylini tanlang", start, "Tarix (*.csv *.pkl *.pickle *.parquet);;Hammasi (*)")
        if f:
            try:
                f = str(Path(f).resolve().relative_to(app_dir()))
            except ValueError:
                pass
            self.hist.setText(f)
            self._hist_changed()

    def _hist_changed(self) -> None:
        s = self.app.settings
        s.set("SL_HISTORY", self.hist.text().strip())
        s.save()
        df = D.history_preview(s.resolve(self.hist.text().strip()))
        if df is None:
            self.hist_info.setText("⚠ Fayl topilmadi yoki o'qib bo'lmadi")
        else:
            n = df.attrs.get("bars", len(df))
            days = (df.index[-1] - df.index[0]).days
            self.hist_info.setText("✓ %s sham · %s → %s · %.1f yil" % (
                "{:,}".format(n).replace(",", " "), df.index[0].strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d"),
                days / 365.25))
        self.price.show(df)

    def _budget_changed(self, *_a) -> None:
        sec = self.budget.value() * 30
        n = self.repeat.value()
        self.budget_lbl.setText("%s%s" % (human_secs(sec), ("  ×  %d = %s gacha" % (n, human_secs(sec * n))) if n > 1 else ""))
        import sl_core as sc
        t = sc.eff_min_t(sc.Cfg(trials=n, min_t=float(self.app.settings.get("SL_MIN_T"))))
        self.t_lbl.setText("Holdout t chegarasi: %.2f%s" % (t, " (qattiqlashtirilgan)" if n > 1 else ""))

    def _toggle_log(self, on=None) -> None:
        on = not self.log.isVisible() if on is None else on
        self.log.setVisible(on)
        self.log_toggle.setText("Yashirish" if on else "Ko'rsatish")

    def start(self) -> None:
        s = self.app.settings
        if self.app.learn.running:
            return
        s.set("SL_MODE", self.mode())
        s.set("SL_HISTORY", self.hist.text().strip())
        s.set("SL_BUDGET_SEC", self.budget.value() * 30)
        s.set("SL_REPEAT", self.repeat.value())
        s.set("SL_CONFIRM", self.confirm.text().strip())
        s.save()
        if D.history_preview(s.resolve(s.get("SL_HISTORY"))) is None:
            self.banner.set("Tarix fayli topilmadi. 2-qadamda faylni tanlang.", "critical")
            return
        self.log.clear()
        self._reset_progress()
        self.t0 = time.time()
        self.banner.set("")
        args = ["--learn"] + (["--force"] if self.force.isChecked() else [])
        self.app.learn.start(args, s.env())
        self.timer.start(500)
        self._set_running(True)
        from PySide6.QtWidgets import QScrollArea
        QTimer.singleShot(50, lambda: self.findChild(QScrollArea).ensureWidgetVisible(self.progress_card, 0, 0))

    def _set_running(self, on: bool) -> None:
        self.start_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        for w in list(self.mode_cards.values()) + [self.hist, self.budget, self.repeat, self.confirm, self.force]:
            w.setEnabled(not on)
        self.state_pill.set("O'rganmoqda…" if on else "Tayyor", "busy" if on else "idle")
        self.app.refresh_nav()

    # ------------------------------------------------------------ jarayon
    def _reset_progress(self) -> None:
        self.frac, self.px, self.py, self.fams = 0.0, [], [], []
        self.attempt, self.of = 1, 1
        self.bar.setValue(0)
        self.eta.setText("")
        self.step_lbl.setText("")
        self.pchart.show([], [])

    def _on_line(self, ln: str) -> None:
        self.log.appendPlainText(ln)

    def _on_progress(self, d: dict) -> None:
        a = d.get("args", [])
        self.attempt, self.of = int(d.get("attempt", 1)), int(d.get("of", 1))
        mode = self.mode()
        budget = self.budget.value() * 30
        el = float(d.get("elapsed", 0))
        f = min(0.97, el / max(1.0, budget))
        if mode == "genetic" and len(a) >= 3:
            gen, best = int(a[0]), float(a[1])
            f = max(f, (gen + 1) / 80.0) if el < budget * 0.8 else f
            self.px.append(gen + 1)
            self.py.append(best)
            self.step_lbl.setText("Avlod %d · eng yaxshi train t = %.2f · %d ta qoida tekshirildi" % (gen + 1, best, int(a[2])))
            self.pchart.show(self.px, self.py, "avlod")
        elif mode == "optimizer" and len(a) >= 4:
            fn, wi, nw, s_tr = str(a[0]), int(a[1]), int(a[2]), float(a[3])
            if fn not in self.fams:
                self.fams.append(fn)
            k = self.fams.index(fn)
            f = max(f, (k * nw + wi + 1) / (3.0 * nw))
            self.px.append(len(self.px) + 1)
            self.py.append(s_tr)
            self.step_lbl.setText("Oila «%s» (%d/3) · oyna %d/%d · train baho %.2f" % (fn, k + 1, wi + 1, nw, s_tr))
            self.pchart.show(self.px, self.py, "oyna")
        elif mode == "ml":
            f = max(f, 0.5)
            self.step_lbl.setText("Model o'rgatildi, ehtimol chegarasi validatsiyada tanlanmoqda…")
        self.frac = max(self.frac, min(0.99, f))

    def _tick(self) -> None:
        el = time.time() - getattr(self, "t0", time.time())
        budget = self.budget.value() * 30
        within = min(0.97, (el - (self.attempt - 1) * budget) / max(1.0, budget))
        cur = max(self.frac, within if within > 0 else 0)
        total = ((self.attempt - 1) + cur) / max(1, self.of)
        self.bar.setValue(int(total * 1000))
        left = max(0, budget * self.of - el) if total < 0.99 else 0
        self.eta.setText("%s%s · o'tdi %s · qoldi ≈ %s" % (
            ("urinish %d/%d · " % (self.attempt, self.of)) if self.of > 1 else "", "%d%%" % (total * 100), human_secs(el),
            human_secs(left)))
        if self.mode() == "ml" and not self.step_lbl.text():
            self.step_lbl.setText("Xususiyatlar va yorliqlar hisoblanmoqda, XGBoost o'rgatilmoqda…")

    def _on_finished(self, code: int, last: str) -> None:
        self.timer.stop()
        self._set_running(False)
        if code == 0:
            self.bar.setValue(1000)
            rep = D.latest_report(self.app.settings.state_dir(), self.mode())
            ok = bool(rep and rep.get("passed"))
            self.state_pill.set("Darvozadan o'tdi" if ok else "Darvozadan o'tmadi", "good" if ok else "critical")
            self.banner.set(("Strategiya tekshiruvdan o'tdi va saqlandi — jonli savdoda ishlatiladi." if ok else
                             "Strategiya tegilmagan davrda ustunlik ko'rsatmadi, savdoga qo'yilmaydi. Bu himoya ishlayapti — "
                             "batafsil sabablar «Natijalar» sahifasida.") + "", "good" if ok else "warning")
            self.app.on_learned(self.mode())
        else:
            self.state_pill.set("Xato / to'xtatildi", "critical")
            self.banner.set("O'rganish tugamadi (kod %d). %s" % (code, html.escape(last)), "critical")
            self._toggle_log(True)

    def refresh(self) -> None:
        for mc in self.mode_cards.values():
            mc._style(mc.isChecked())
        if not self.app.learn.running:
            self.price.show(D.history_preview(self.app.settings.resolve(self.hist.text().strip())))
        self.pchart.show(self.px, self.py, "avlod" if self.mode() == "genetic" else "oyna")
