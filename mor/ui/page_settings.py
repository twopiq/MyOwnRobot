from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QProgressBar, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import __version__
from ..settings import FIELDS, Field
from . import theme as T
from . import widgets as W
from .page import Page


class SettingsPage(Page):
    key, title = "settings", "Sozlamalar"

    def __init__(self, win):
        super().__init__(win)
        self.root.addWidget(W.page_header(self.title))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(24, 20, 24, 20)
        g.setSpacing(16)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        sc.setWidget(body)
        self.root.addWidget(sc, 1)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(16)
        right.setSpacing(16)
        g.addLayout(left, 0, 0, Qt.AlignTop)
        g.addLayout(right, 0, 1, Qt.AlignTop)
        self.ctrl: Dict[str, Any] = {}
        groups = {}
        for f in FIELDS:
            groups.setdefault(f.group, []).append(f)
        for name in ("O'qitish", "Model", "Muhit", "Xotira"):
            left.addWidget(self._card(name, groups[name]))
        for name in ("Jonli savdo", "MT5 hisob"):
            right.addWidget(self._card(name, groups[name]))
        right.addWidget(self._update_card())
        left.addStretch(1)
        right.addStretch(1)

    def _card(self, name: str, fields) -> W.Card:
        c = W.Card(name)
        for f in fields:
            c.add(self._row(f))
        return c

    def _row(self, f: Field) -> QWidget:
        w = QFrame()
        w.setObjectName("row")
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 10, 16, 10)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(W.label(f.label))
        if f.help:
            col.addWidget(W.label(f.help, "dim", wrap=True))
        h.addLayout(col, 1)
        val = self.settings[f.key]
        if f.kind == "bool":
            c = QCheckBox()
            c.setChecked(bool(val))
            c.toggled.connect(lambda v, k=f.key: self._set(k, bool(v)))
        elif f.kind == "int":
            c = QSpinBox()
            c.setRange(int(f.lo), int(f.hi))
            c.setSingleStep(int(f.step))
            c.setValue(int(val))
            c.setSuffix(f.suffix)
            c.valueChanged.connect(lambda v, k=f.key: self._set(k, int(v)))
        elif f.kind == "float":
            c = QDoubleSpinBox()
            c.setDecimals(4 if f.step < 0.01 else 2)
            c.setRange(f.lo, f.hi)
            c.setSingleStep(f.step)
            c.setValue(float(val))
            c.setSuffix(f.suffix)
            c.valueChanged.connect(lambda v, k=f.key: self._set(k, float(v)))
        elif f.kind == "choice":
            c = QComboBox()
            c.addItems(list(f.choices))
            c.setCurrentText(str(val))
            c.currentTextChanged.connect(lambda v, k=f.key: self._set(k, v))
        else:
            c = QLineEdit(str(val))
            if f.kind == "secret":
                c.setEchoMode(QLineEdit.Password)
            c.editingFinished.connect(lambda k=f.key, e=c: self._set(k, e.text().strip()))
        if f.kind in ("int", "float", "str", "path", "secret", "choice"):
            c.setFixedWidth(200 if f.kind != "path" else 180)
        h.addWidget(c, 0, Qt.AlignVCenter)
        if f.kind == "path":
            b = W.button("Tanlash")
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, e=c, k=f.key: self._browse(e, k))
            h.addWidget(b)
        self.ctrl[f.key] = c
        return w

    def _browse(self, edit: QLineEdit, key: str) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "MT5 terminal", "", "terminal64.exe (terminal64.exe);;Hammasi (*)")
        if p:
            edit.setText(p)
            self._set(key, p)

    def _set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.settings.save()
        if key in ("tf", "symbols", "lr", "gamma", "sl_atr"):
            self.win.pages["training"].refresh()

    # ------------------------------------------------------------ yangilanish
    def _update_card(self) -> W.Card:
        mgr = self.win.updates
        c = W.Card("Yangilanish")
        self.u_ver = W.KV("Joriy versiya", __version__)
        self.u_state = W.KV("Holat", "—")
        c.add(self.u_ver)
        c.add(self.u_state)
        self.u_notes = W.label("", "muted", wrap=True)
        self.u_notes.setContentsMargins(16, 8, 16, 0)
        c.add(self.u_notes)
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 12, 16, 12)
        self.u_prog = QProgressBar()
        self.u_prog.setRange(0, 100)
        self.u_prog.setTextVisible(False)
        self.u_prog.setVisible(False)
        self.u_check = W.button("Tekshirish", on=lambda: mgr.check(False))
        self.u_act = W.button("Yuklab olish", "primary", on=self._act)
        self.u_act.setVisible(False)
        h.addWidget(self.u_prog, 1)
        h.addWidget(self.u_check)
        h.addWidget(self.u_act)
        c.add(bar)
        auto = QCheckBox("Avtomatik tekshirish")
        auto.setChecked(mgr.settings()["auto"])
        auto.toggled.connect(lambda v: mgr.save_settings({"auto": bool(v)}))
        aw = QWidget()
        al = QHBoxLayout(aw)
        al.setContentsMargins(16, 4, 16, 14)
        al.addWidget(auto)
        c.add(aw)
        mgr.changed.connect(self.sync_update)
        self.sync_update()
        return c

    def _act(self) -> None:
        m = self.win.updates
        if m.state in ("ready", "full_ready"):
            m.restart()
        else:
            m.download()

    def sync_update(self) -> None:
        m = self.win.updates
        self.u_state.set(m.message or "tekshirilmagan", {"error": "down", "ready": "up", "full_ready": "up", "available": "accent"}.get(m.state, ""))
        self.u_notes.setText(m.info.notes if m.info is not None else "")
        self.u_prog.setVisible(m.state == "downloading")
        self.u_prog.setValue(m.pct)
        self.u_act.setVisible(m.state in ("available", "ready", "full_ready") and m.info is not None)
        self.u_act.setText("Qayta ochish" if m.state in ("ready", "full_ready") else "Yuklab olish")
        self.u_check.setEnabled(m.state not in ("checking", "downloading"))
