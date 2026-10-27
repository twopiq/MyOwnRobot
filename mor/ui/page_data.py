from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QInputDialog, QMenu, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from .. import importers, paths
from ..db import Database
from . import theme as T
from . import widgets as W
from .page import Page, fdate
from .workers import Job

TF_MIN = importers.TF_MIN


class DropArea(QFrame):
    def __init__(self, on_files):
        super().__init__()
        self.on_files = on_files
        self.setAcceptDrops(True)
        self.setStyleSheet("QFrame { border: 1px dashed #2f3a4b; border-radius: 8px; background: transparent; }"
                           "QLabel { border: none; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 24, 20, 24)
        v.setSpacing(4)
        a = W.label("CSV faylni shu yerga tashlang", "")
        a.setAlignment(Qt.AlignCenter)
        b = W.label("MT5 eksport formati: DATE, TIME, OPEN, HIGH, LOW, CLOSE, TICKVOL, SPREAD", "dim")
        b.setAlignment(Qt.AlignCenter)
        b.setWordWrap(True)
        v.addWidget(a)
        v.addWidget(b)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith((".csv", ".txt"))]
        if files:
            self.on_files(files)


class ImportDialog(QDialog):
    def __init__(self, files: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fayllarni import qilish")
        self.setMinimumWidth(480)
        f = QFormLayout(self)
        f.setContentsMargins(20, 20, 20, 16)
        f.setSpacing(12)
        names = ", ".join(os.path.basename(x) for x in files[:4]) + (" …" if len(files) > 4 else "")
        f.addRow(W.label("Fayllar:", "muted"), W.label("%d ta: %s" % (len(files), names), wrap=True))
        self.sym = QLineEdit()
        self.sym.setPlaceholderText("fayl nomidan (masalan XAUUSD_M1.csv → XAUUSD)")
        self.tf = QComboBox()
        self.tf.addItem("Asl davr (o'zgartirmasdan)", "")
        for t in ("M5", "M15", "M30", "H1"):
            self.tf.addItem("%s ga jamlash" % t, t)
        self.tf.setCurrentIndex(2)
        self.tz = QDoubleSpinBox()
        self.tz.setRange(-12, 14)
        self.tz.setSingleStep(1)
        self.tz.setSuffix(" soat")
        f.addRow(W.label("Instrument nomi", "muted"), self.sym)
        f.addRow(W.label("Taymfreym", "muted"), self.tf)
        f.addRow(W.label("Vaqt siljishi", "muted"), self.tz)
        f.addRow(W.label("", "dim"), W.label("Fayldagi vaqt server vaqti bo'lsa, UTC ga o'tkazish uchun siljishni kiriting (masalan, 3).", "dim", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setText("Import")
        bb.button(QDialogButtonBox.Ok).setProperty("kind", "primary")
        bb.button(QDialogButtonBox.Cancel).setText("Bekor")
        f.addRow(bb)

    def values(self) -> Dict[str, Any]:
        return {"symbol": self.sym.text().strip().upper() or None, "target_tf": self.tf.currentData() or None,
                "tz": self.tz.value()}


class Mt5Dialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MT5 dan tarix yuklash")
        self.setMinimumWidth(480)
        f = QFormLayout(self)
        f.setContentsMargins(20, 20, 20, 16)
        f.setSpacing(12)
        self.syms = QLineEdit("XAUUSD, EURUSD, GBPUSD")
        self.tf = QComboBox()
        for t in ("M1", "M5", "M15", "M30", "H1"):
            self.tf.addItem(t)
        self.tf.setCurrentText("M15")
        self.a = QDateEdit(QDate(2022, 1, 1))
        self.b = QDateEdit(QDate.currentDate())
        for d in (self.a, self.b):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        f.addRow(W.label("Simvollar", "muted"), self.syms)
        f.addRow(W.label("Taymfreym", "muted"), self.tf)
        f.addRow(W.label("Boshlanish", "muted"), self.a)
        f.addRow(W.label("Tugash", "muted"), self.b)
        f.addRow(W.label("", "dim"), W.label("MT5 terminal ochiq va hisobga kirilgan bo'lishi kerak (Sozlamalar → MT5 hisob).", "dim", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setText("Yuklash")
        bb.button(QDialogButtonBox.Cancel).setText("Bekor")
        f.addRow(bb)

    def values(self) -> Dict[str, Any]:
        return {"symbols": [s.strip().upper() for s in self.syms.text().split(",") if s.strip()], "tf": self.tf.currentText(),
                "start": self.a.date().toString("yyyy-MM-dd"), "end": self.b.date().toString("yyyy-MM-dd")}


class DataPage(Page):
    key, title = "data", "Ma'lumotlar bazasi"

    def __init__(self, win):
        super().__init__(win)
        self.p_db = W.pill("")
        self.b_mt5 = W.button("MT5 dan yuklash", on=self.mt5)
        self.b_imp = W.button("Fayl import qilish", "primary", on=self.pick_files)
        self.root.addWidget(W.page_header(self.title, [self.p_db], [self.b_mt5, self.b_imp]))
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(24, 20, 24, 20)
        g.setSpacing(16)
        g.setColumnStretch(0, 22)
        g.setColumnStretch(1, 10)
        self.root.addWidget(body, 1)
        self.sub = W.label("", "muted")
        c1 = W.Card("Datasetlar", self.sub)
        self.table = W.Table(["Instr.", "TF", "Shamlar", "Boshlanish", "Tugash", "Spred", "Holat"],
                             mono_cols=(2, 3, 4, 5))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.menu)
        c1.add(self.table, 1)
        g.addWidget(c1, 0, 0, 2, 1)
        c2 = W.Card("Yangi dataset")
        self.drop = DropArea(self.import_files)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 16, 16, 16)
        wl.addWidget(self.drop)
        self.status = W.label("", "muted", wrap=True)
        wl.addWidget(self.status)
        c2.add(wrap)
        g.addWidget(c2, 0, 1)
        c3 = W.Card("Qo'shimcha manbalar")
        self.src_cal = self._source("calendar", "Iqtisodiy kalendar", "", "Import", self.import_calendar,
                                    extra=[("MQL5 skript", self.save_script)])
        self.src_spr = self._source("spread", "Spred tarixi", "", None, None)
        self.src_news = self._source("news", "Yangiliklar", "Manba ulanmagan", None, None)
        for s in (self.src_cal, self.src_spr, self.src_news):
            c3.add(s["w"])
        g.addWidget(c3, 1, 1)
        g.setRowStretch(1, 1)

    def _source(self, ic, title, sub, btn, on, extra=()):
        w = QFrame()
        w.setObjectName("row")
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)
        i = QLabel()
        i.setPixmap(T.svg(ic, T.MUTED, 18))
        i.setFixedWidth(22)
        col = QVBoxLayout()
        col.setSpacing(2)
        t, s = W.label(title), W.label(sub, "dim")
        col.addWidget(t)
        col.addWidget(s)
        h.addWidget(i)
        h.addLayout(col, 1)
        tg = W.tag("")
        h.addWidget(tg)
        b = None
        if btn:
            b = W.button(btn, on=on)
            b.setFixedHeight(28)
            h.addWidget(b)
        for text, cb in extra:
            eb = W.button(text, on=cb)
            eb.setFixedHeight(28)
            h.addWidget(eb)
        return {"w": w, "sub": s, "tag": tg, "btn": b}

    # ------------------------------------------------------------ yangilash
    def refresh(self) -> None:
        ds = self.db.datasets()
        size = os.path.getsize(paths.db_path()) / 1e6 if paths.db_path().exists() else 0
        self.p_db.setText("robot.db · %.0f MB" % size)
        rows = []
        for d in ds:
            span_min = (d["end"] - d["start"]) / 60.0
            exp = span_min / TF_MIN.get(d["tf"], 15) * (5 / 7) * (23 / 24)
            cov = d["bars"] / exp if exp > 0 else 0
            spr = self.db.con.execute("SELECT AVG(spread) FROM bars WHERE symbol=? AND tf=?", (d["symbol"], d["tf"])).fetchone()[0] or 0
            if d["bars"] < 3000:
                st = ("Kam ma'lumot", "down")
            elif cov >= 0.9:
                st = ("Tayyor", "up")
            else:
                st = ("Bo'shliqlar %.0f%%" % (cov * 100), "warn")
            rows.append([d["symbol"], d["tf"], "{:,}".format(d["bars"]).replace(",", " "), fdate(d["start"])[:10], fdate(d["end"])[:10],
                         "%.5g" % spr, st])
        self.table.fill(rows, [11, 9, 11, 14, 14, 9, 14])
        self.sub.setText("%d dataset" % len(ds) + ((" · " + min(fdate(d["start"])[:10] for d in ds) + " → " +
                                                  max(fdate(d["end"])[:10] for d in ds)) if ds else ""))
        ev = self.db.count("events")
        self.src_cal["sub"].setText("%d voqea" % ev if ev else "MQL5 skript → CSV → Import")
        self.src_cal["tag"].setText("Ulangan" if ev else "Bo'sh")
        W.set_tone(self.src_cal["tag"], "up" if ev else "")
        has_spr = any(d["bars"] for d in ds)
        self.src_spr["sub"].setText("Har shamdagi spred (shamlar bilan birga saqlanadi)")
        self.src_spr["tag"].setText("Ulangan" if has_spr else "Bo'sh")
        W.set_tone(self.src_spr["tag"], "up" if has_spr else "")
        self.src_news["tag"].setText("O'chiq")

    def menu(self, pos) -> None:
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        sym, tf = self.table.item(r, 0).text(), self.table.item(r, 1).text()
        m = QMenu(self)
        act = m.addAction("«%s %s» ni o'chirish" % (sym, tf))
        if m.exec(self.table.viewport().mapToGlobal(pos)) is act:
            if QMessageBox.question(self, "O'chirish", "%s %s datasetini bazadan o'chirasizmi?" % (sym, tf)) == QMessageBox.Yes:
                self.db.delete_dataset(sym, tf)
                self.win.changed()

    # ------------------------------------------------------------ import
    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "CSV fayllarni tanlang", "", "CSV (*.csv *.txt);;Hammasi (*)")
        if files:
            self.import_files(files)

    def import_files(self, files: List[str]) -> None:
        dlg = ImportDialog(files, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        db_file = str(paths.db_path())

        def work(emit, stopped):
            db = Database(db_file)
            out = []
            try:
                for f in files:
                    emit({"msg": "O'qilmoqda: %s" % os.path.basename(f)})
                    out.append(importers.import_csv(db, f, symbol=v["symbol"] if len(files) == 1 else None,
                                                    target_tf=v["target_tf"], tz_offset_hours=v["tz"],
                                                    progress=lambda m: emit({"msg": m})))
            finally:
                db.close()
            return out
        self._run(work, "Import")

    def save_script(self) -> None:
        from ..mql import CALENDAR_SCRIPT
        f, _ = QFileDialog.getSaveFileName(self, "MQL5 skriptni saqlash", "ExportCalendar.mq5", "MQL5 (*.mq5)")
        if not f:
            return
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(CALENDAR_SCRIPT)
        QMessageBox.information(
            self, "MQL5 skript saqlandi",
            "Keyingi qadamlar:\n1) Faylni MT5 → Fayl → Ma'lumotlar papkasini ochish → MQL5 → Scripts ichiga ko'chiring.\n"
            "2) MetaEditor'da oching va F7 (kompilyatsiya) bosing.\n"
            "3) MT5'da skriptni grafikka tashlang (Navigator → Scripts).\n"
            "4) Natija MQL5/Files/calendar.csv — uni shu yerdagi «Import» bilan yuklang.")

    def import_calendar(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Kalendar CSV", "", "CSV (*.csv *.txt)")
        if not f:
            return
        tz, ok = QInputDialog.getDouble(
            self, "Vaqt siljishi", "Kalendar vaqti UTC dan necha soat oldinda?\n(narx CSV'ni import qilganda kiritgan qiymatingiz bilan bir xil;\n"
            "narxni «MT5 dan yuklash» orqali olgan bo'lsangiz — 0)", 0, -12, 14, 1)
        if not ok:
            return
        db_file = str(paths.db_path())

        def work(emit, stopped):
            db = Database(db_file)
            try:
                return [{"events": importers.import_calendar_csv(db, f, tz)}]
            finally:
                db.close()
        self._run(work, "Kalendar")

    def mt5(self) -> None:
        dlg = Mt5Dialog(self.settings, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        s = self.settings
        db_file = str(paths.db_path())

        def work(emit, stopped):
            db = Database(db_file)
            out = []
            try:
                for sym in v["symbols"]:
                    if stopped():
                        break
                    emit({"msg": "MT5: %s yuklanmoqda…" % sym})
                    try:
                        login = int(str(s["login"]).strip() or 0)
                    except ValueError:
                        login = 0
                    out.append(importers.mt5_download(db, sym, v["tf"], v["start"], v["end"], s["terminal"], login,
                                                      s["password"], s["server"], lambda m: emit({"msg": m})))
            finally:
                db.close()
            return out
        self._run(work, "MT5")

    def _run(self, fn, name: str) -> None:
        if getattr(self, "job", None) is not None:
            return
        self.job = Job(fn, self)
        self.job.event.connect(lambda e: self.status.setText(e.get("msg", "")))
        self.job.finished_with.connect(lambda res, err: self._done(name, res, err))
        for b in (self.b_imp, self.b_mt5):
            b.setEnabled(False)
        self.status.setText(name + " boshlandi…")
        self.job.start()

    def _done(self, name, res, err) -> None:
        self.job = None
        for b in (self.b_imp, self.b_mt5):
            b.setEnabled(True)
        if err is not None:
            self.status.setText("Xato: %s" % err)
            QMessageBox.warning(self, name, str(err))
        else:
            self.status.setText("%s tugadi: %s" % (name, "; ".join(
                ("%s %s — %s sham" % (r["symbol"], r["tf"], "{:,}".format(r["bars"]).replace(",", " "))) if "bars" in r
                else ("%d voqea" % r["events"]) for r in res)))
            self.win.changed()
