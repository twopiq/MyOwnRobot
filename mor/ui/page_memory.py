from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from . import theme as T
from . import widgets as W
from .page import Page, fdate


class LessonRow(QFrame):
    """Qonuniyat qatori. Balandligi aniq hisoblanadi (o'ralgan matnli QLabel scroll ichida siqilib ketmasligi uchun)."""
    WRAP = 270

    def __init__(self, x):
        super().__init__()
        self.setObjectName("row")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)
        top = QHBoxLayout()
        kind = W.tag("Qochish" if x["kind"] == "avoid" else "Afzal", "down" if x["kind"] == "avoid" else "up")
        st = {"verified": ("Tasdiqlangan", "up"), "rejected": ("Rad etilgan", ""), "candidate": ("Nomzod", "warn")}[x["status"]]
        top.addWidget(kind)
        top.addWidget(W.tag(*st))
        top.addStretch(1)
        v.addLayout(top)
        t = W.label(x["text"], wrap=True)
        th = t.fontMetrics().boundingRect(0, 0, self.WRAP, 2000, Qt.TextWordWrap, x["text"]).height() + 6
        t.setFixedHeight(th)
        v.addWidget(t)
        lines = ["o'rganish:   n %d · %+.2f R · t %.1f" % (x["n"], x["exp"], x["t"]),
                 "tasdiqlash: n %d · %+.2f R · t %.1f" % (x["oos_n"], x["oos_exp"], x["oos_t"])]
        for ln in lines:
            m = W.label(ln, "dim")
            m.setFont(T.mono(11))
            m.setStyleSheet("color: %s;" % T.MUTED)
            m.setFixedHeight(16)
            v.addWidget(m)
        self.setFixedHeight(12 + 20 + 6 + th + 6 + 16 + 6 + 16 + 12 + 4)


class MemoryPage(Page):
    key, title = "memory", "Tajriba xotirasi"

    def __init__(self, win):
        super().__init__(win)
        self.sub = W.label("", "muted")
        self.root.addWidget(W.page_header(self.title, [self.sub]))
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(24, 20, 24, 20)
        g.setSpacing(16)
        g.setColumnStretch(0, 14)
        g.setColumnStretch(1, 11)
        self.root.addWidget(body, 1)
        c1 = W.Card()
        bar = QFrame()
        bar.setObjectName("row")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(8)
        self.grp = QButtonGroup(self)
        self.chips = {}
        for i, (key, text) in enumerate((("all", "Hammasi"), ("win", "Yutuqlar"), ("loss", "Xatolar"), ("worst", "Eng katta yo'qotish"))):
            b = W.button(text, "chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.grp.addButton(b)
            self.chips[key] = b
            h.addWidget(b)
            b.clicked.connect(self.refresh)
        h.addStretch(1)
        self.cb_sym = QComboBox()
        self.cb_sym.setMinimumWidth(130)
        self.cb_sym.currentIndexChanged.connect(self.refresh)
        self.cb_split = QComboBox()
        for k, t in (("", "Barcha davrlar"), ("train", "O'rganish"), ("val", "Tasdiqlash"), ("val_explore", "Tasdiq. (tadqiqot)"), ("test", "Test"), ("live", "Jonli")):
            self.cb_split.addItem(t, k)
        self.cb_split.currentIndexChanged.connect(self.refresh)
        h.addWidget(self.cb_sym)
        h.addWidget(self.cb_split)
        c1.add(bar)
        self.table = W.Table(["Sana (UTC)", "Instr.", "Yo'n.", "R", "MAE", "MFE", "Sham", "Sabab", "Davr"], mono_cols=(0, 3, 4, 5, 6))
        c1.add(self.table, 1)
        g.addWidget(c1, 0, 0)
        self.ls_count = W.tag("", "up")
        c2 = W.Card("Topilgan qonuniyatlar", self.ls_count)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.holder = QWidget()
        self.hl = QVBoxLayout(self.holder)
        self.hl.setContentsMargins(0, 0, 0, 0)
        self.hl.setSpacing(0)
        self.scroll.setWidget(self.holder)
        c2.add(self.scroll, 1)
        g.addWidget(c2, 0, 1)

    def refresh(self) -> None:
        db = self.db
        st = db.experience_stats()
        self.sub.setText("%s bitim · %d instrument" % ("{:,}".format(st["n"]).replace(",", " "), st["symbols"]))
        cur = self.cb_sym.currentText()
        syms = [r[0] for r in db.con.execute("SELECT DISTINCT symbol FROM experiences ORDER BY symbol")]
        self.cb_sym.blockSignals(True)
        self.cb_sym.clear()
        self.cb_sym.addItem("Barcha instrumentlar", "")
        for s in syms:
            self.cb_sym.addItem(s, s)
        i = self.cb_sym.findText(cur)
        self.cb_sym.setCurrentIndex(max(0, i))
        self.cb_sym.blockSignals(False)
        mode = next(k for k, b in self.chips.items() if b.isChecked())
        rows = db.experiences(split=self.cb_split.currentData() or None, symbol=self.cb_sym.currentData() or None,
                              outcome={"win": "win", "loss": "loss"}.get(mode), limit=300,
                              order="r ASC" if mode == "worst" else "ts_close DESC")
        names = {"train": "o'rganish", "val": "tasdiq", "val_explore": "tasdiq.", "test": "test", "live": "jonli"}
        self.table.fill([[fdate(r["ts_close"], True), r["symbol"], "BUY" if r["side"] > 0 else "SELL",
                          ("%+.2f" % r["r"], "up" if r["r"] > 0 else "down"), "%.2f" % r["mae"], "%.2f" % r["mfe"],
                          str(r["bars_held"]), r["reason"], names.get(r["split"], r["split"])] for r in rows],
                         [13, 12, 8, 9, 9, 9, 8, 9, 11])
        while self.hl.count():
            w = self.hl.takeAt(0).widget()
            if w:
                w.deleteLater()
        ls = db.lessons()
        ver = [x for x in ls if x["status"] == "verified"]
        self.ls_count.setText("%d tasdiqlangan" % len(ver))
        if not ls:
            e = W.label("Qonuniyatlar o'qitish tugagach shu yerda paydo bo'ladi.", "dim", wrap=True)
            e.setContentsMargins(16, 16, 16, 16)
            self.hl.addWidget(e)
        total = 0
        for x in ls:
            row = LessonRow(x)
            total += row.height()
            self.hl.addWidget(row)
        self.hl.addStretch(1)
        self.holder.setMinimumHeight(total + 8)
