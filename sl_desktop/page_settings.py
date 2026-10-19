"""Sozlamalar: barcha robot parametrlari guruhlar bo'yicha, har biri izoh bilan; mavzu (yorug'/qorong'i)."""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import widgets as W
from .settings import FIELDS, GROUPS, Field


class SettingsPage(W.Page):
    def __init__(self, app):
        super().__init__("Sozlamalar", "O'zgarishlar keyingi o'rganish yoki jonli ishga tushirishda qo'llanadi")
        self.app = app
        self.theme = QComboBox()
        self.theme.addItem("🌙  Qorong'i mavzu", "dark")
        self.theme.addItem("☀  Yorug' mavzu", "light")
        self.theme.setMinimumWidth(190)
        self.theme.setCurrentIndex(0 if app.settings.ui.get("theme", "dark") == "dark" else 1)
        self.theme.currentIndexChanged.connect(lambda *_: app.apply_theme(self.theme.currentData()))
        self.head_right.addWidget(self.theme)
        reset = QPushButton("Standart qiymatlar")
        reset.clicked.connect(self._reset)
        self.head_right.addWidget(reset)
        save = QPushButton("💾  Saqlash")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        self.head_right.addWidget(save)

        from .update_ui import UpdateCard
        self.update_card = UpdateCard(app)
        self.lay.addWidget(self.update_card)
        self.editors: Dict[str, QWidget] = {}
        for gk, gname, gdesc in GROUPS:
            card = W.Card(gname, gdesc)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(14)
            fs = [f for f in FIELDS if f.group == gk]
            for i, f in enumerate(fs):
                box = QWidget()
                v = QVBoxLayout(box)
                v.setContentsMargins(0, 0, 0, 0)
                v.setSpacing(4)
                lb = W.label(f.label, "text2")
                lb.setToolTip(f.key)
                v.addWidget(lb)
                ed = self._editor(f)
                self.editors[f.key] = ed
                v.addWidget(ed)
                if f.help:
                    v.addWidget(W.label(f.help, "muted", wrap=True))
                v.addStretch(1)
                grid.addWidget(box, i // 2, i % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            card.body.addLayout(grid)
            self.lay.addWidget(card)
        self.lay.addStretch(1)
        self.load()

    def _editor(self, f: Field) -> QWidget:
        if f.kind == "bool":
            w = QCheckBox("Yoqilgan")
        elif f.kind == "choice":
            w = QComboBox()
            w.addItems(list(f.choices))
        elif f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.lo), int(min(f.hi, 2 ** 31 - 1)))
            w.setSingleStep(int(f.step))
            w.setSuffix(f.suffix)
        elif f.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(2 if f.step < 1 else 1)
            w.setRange(f.lo, f.hi)
            w.setSingleStep(f.step)
            w.setSuffix(f.suffix)
        elif f.kind == "file":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            e = QLineEdit()
            b = QPushButton("📁")
            b.setFixedWidth(44)
            b.clicked.connect(lambda _=False, e=e: self._browse(e))
            h.addWidget(e, 1)
            h.addWidget(b)
            w.edit = e
        else:
            w = QLineEdit()
            if "TOKEN" in f.key:
                w.setEchoMode(QLineEdit.EchoMode.Password)
        w.setToolTip(f.help)
        return w

    def _browse(self, e: QLineEdit) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Fayl tanlash")
        if f:
            e.setText(f)

    def _set(self, f: Field, v: Any) -> None:
        w = self.editors[f.key]
        if f.kind == "bool":
            w.setChecked(bool(v))
        elif f.kind == "choice":
            w.setCurrentText(str(v))
        elif f.kind == "int":
            w.setValue(int(v or 0))
        elif f.kind == "float":
            w.setValue(float(v or 0))
        elif f.kind == "file":
            w.edit.setText(str(v or ""))
        else:
            w.setText(str(v or ""))

    def _get(self, f: Field) -> Any:
        w = self.editors[f.key]
        if f.kind == "bool":
            return w.isChecked()
        if f.kind == "choice":
            return w.currentText()
        if f.kind in ("int", "float"):
            return w.value()
        if f.kind == "file":
            return w.edit.text().strip()
        return w.text().strip()

    def load(self) -> None:
        for f in FIELDS:
            self._set(f, self.app.settings.get(f.key))

    def save(self) -> None:
        s = self.app.settings
        warn = []
        for f in FIELDS:
            v = self._get(f)
            if f.key == "SL_DEMO_ONLY" and not v and s.get(f.key):
                warn.append("«Faqat DEMO» o'chirildi — robot REAL hisobda savdo qilishi mumkin.")
            if f.key == "SL_REQUIRE_PASS" and not v and s.get(f.key):
                warn.append("Tekshirilmagan strategiya bilan savdoga ruxsat berildi.")
            s.set(f.key, v)
        if warn and QMessageBox.warning(self, "Diqqat", "\n".join(warn) + "\n\nSaqlansinmi?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            s.load()
            self.load()
            return
        s.save()
        self.app.toast("Sozlamalar saqlandi")
        self.app.refresh_all()

    def _reset(self) -> None:
        if QMessageBox.question(self, "Standart qiymatlar", "Barcha sozlamalar standart qiymatga qaytarilsinmi?") \
                == QMessageBox.StandardButton.Yes:
            for f in FIELDS:
                self._set(f, f.default)

    def refresh(self) -> None:
        if not self.isVisible():
            self.load()
