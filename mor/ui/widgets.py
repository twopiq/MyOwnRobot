"""Umumiy vidjetlar: karta, KPI, belgi, jadval, chiziqli grafik."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QSpacerItem,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme as T


def label(text: str = "", role: str = "", tone: str = "", mono: bool = False, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if tone:
        lb.setProperty("tone", tone)
        if role not in ("tag", "pill"):
            lb.setStyleSheet("color: %s;" % T.tone_color(tone))
    if mono:
        lb.setFont(T.mono(22 if role == "num" else 12))
    lb.setWordWrap(wrap)
    if role in ("pill", "tag"):
        lb.setFixedHeight(24 if role == "pill" else 20)
        lb.setAlignment(Qt.AlignCenter)
        lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def set_tone(lb: QLabel, tone: str) -> None:
    lb.setProperty("tone", tone)
    if lb.property("role") in ("tag", "pill"):
        lb.style().unpolish(lb)
        lb.style().polish(lb)
    else:
        lb.setStyleSheet("color: %s;" % T.tone_color(tone))


def tag(text: str, tone: str = "") -> QLabel:
    return label(text, "tag", tone)


def button(text: str, kind: str = "", icon: Optional[str] = None, on: Optional[Callable] = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon:
        b.setIcon(T.icon(icon, T.TEXT, 16))
    b.setCursor(Qt.PointingHandCursor)
    if on:
        b.clicked.connect(on)
    return b


class Card(QFrame):
    def __init__(self, title: str = "", right: Optional[QWidget] = None, margins: bool = False):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.head: Optional[QFrame] = None
        self.hl: Optional[QHBoxLayout] = None
        if title:
            self.head = QFrame()
            self.head.setObjectName("cardHead")
            self.hl = QHBoxLayout(self.head)
            self.hl.setContentsMargins(16, 11, 16, 11)
            self.title = label(title, "b")
            self.hl.addWidget(self.title)
            self.hl.addStretch(1)
            if right is not None:
                self.hl.addWidget(right)
            self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.lay.addWidget(self.head)
        self._spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.lay.addItem(self._spacer)
        if margins:
            self.lay.setContentsMargins(16, 14, 16, 14)

    def add(self, w: QWidget, stretch: int = 0) -> None:
        self.lay.insertWidget(self.lay.count() - 1, w, stretch)

    def add_head(self, w: QWidget) -> None:
        if self.hl is not None:
            self.hl.addWidget(w)


class Kpi(Card):
    def __init__(self, title: str, value: str = "—", sub: str = ""):
        super().__init__(margins=False)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(6)
        self.t = label(title, "muted")
        self.v = label(value, "num", mono=True)
        self.s = label(sub, "dim")
        for w in (self.t, self.v, self.s):
            self.lay.addWidget(w)

    def set(self, value: str, sub: Optional[str] = None, tone: str = "") -> None:
        self.v.setText(value)
        self.v.setStyleSheet("color: %s;" % (T.tone_color(tone) if tone else T.TEXT))
        if sub is not None:
            self.s.setText(sub)


class KV(QFrame):
    """Kalit — qiymat qatori (kartalar ichida)."""

    def __init__(self, key: str, value: str = ""):
        super().__init__()
        self.setObjectName("row")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 9, 16, 9)
        self.k = label(key, "muted")
        self.v = label(value, mono=True)
        h.addWidget(self.k)
        h.addStretch(1)
        h.addWidget(self.v)

    def set(self, value: str, tone: str = "") -> None:
        self.v.setText(value)
        self.v.setStyleSheet("color: %s;" % (T.tone_color(tone) if tone else T.TEXT))


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)
        self.setStyleSheet("background: %s;" % T.ROW)


class _KeepTone(QStyledItemDelegate):
    """Tanlangan qatorda ham katakning o'z rangi (yashil/qizil/sariq) saqlansin — oq bo'lib qolmasin."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        fg = index.data(Qt.ForegroundRole)
        if fg is not None:
            option.palette.setBrush(QPalette.HighlightedText, fg if isinstance(fg, QBrush) else QBrush(fg))


class Table(QTableWidget):
    """Dizayndagi jadval: sarlavha kichik harfda, qatorlar 36px, raqamlar mono."""

    def __init__(self, headers: Sequence[str], mono_cols: Iterable[int] = (), stretch_col: Optional[int] = None):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels([h.upper() for h in headers])
        self.mono_cols = set(mono_cols)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(36)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setItemDelegate(_KeepTone(self))
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.stretch_col = stretch_col
        self.weights: List[int] = []
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._apply_weights()

    def _apply_weights(self) -> None:
        n = self.columnCount()
        if not self.weights or n == 0:
            return
        w = list(self.weights) + [100] * (n - len(self.weights))
        tot, avail = sum(w[:n]), max(100, self.viewport().width())
        for j in range(n):
            self.setColumnWidth(j, int(avail * w[j] / tot))

    def fill(self, rows: List[List[Any]], widths: Optional[Sequence[int]] = None) -> None:
        """Katak: str yoki (str, ton) yoki (str, ton, QWidget-emas). ton: up/down/warn/accent/muted."""
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                text, tone = (cell if isinstance(cell, tuple) else (cell, ""))[:2]
                it = QTableWidgetItem(str(text))
                it.setForeground(QColor(T.tone_color(tone) if tone else T.TEXT))
                if j in self.mono_cols:
                    it.setFont(T.mono(12))
                self.setItem(i, j, it)
        if widths:
            self.weights = list(widths)
            self._apply_weights()

    def set_cell_widget(self, r: int, c: int, w: QWidget) -> None:
        self.setCellWidget(r, c, w)


class LineChart(QWidget):
    """Ko'p qatorli chiziqli grafik: setka, nol chizig'i, sichqoncha ustida qiymatlar."""

    def __init__(self, height: int = 220, zero_line: bool = True, fmt: str = "%+.2f"):
        super().__init__()
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.series: List[Dict[str, Any]] = []
        self.zero_line, self.fmt = zero_line, fmt
        self.xlabels: Optional[List[str]] = None
        self._hover: Optional[int] = None
        self.empty_text = "Ma'lumot yo'q"

    def set_series(self, series: List[Dict[str, Any]], xlabels: Optional[List[str]] = None) -> None:
        self.series, self.xlabels = series, xlabels
        self.update()

    def _bounds(self):
        vals = [v for s in self.series for v in s["values"] if v is not None]
        if not vals:
            return 0.0, 1.0
        lo, hi = min(vals), max(vals)
        if self.zero_line:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        if hi - lo < 1e-9:
            hi, lo = hi + 1, lo - 1
        pad = (hi - lo) * 0.08
        return lo - pad, hi + pad

    def _plot_rect(self) -> QRectF:
        return QRectF(46, 12, max(10, self.width() - 62), max(10, self.height() - 34))

    def _n(self) -> int:
        return max((len(s["values"]) for s in self.series), default=0)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot_rect()
        n = self._n()
        if n < 2:
            p.setPen(QColor(T.DIM))
            p.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
            return
        lo, hi = self._bounds()
        X = lambda i: r.left() + r.width() * i / (n - 1)                 # noqa: E731
        Y = lambda v: r.bottom() - r.height() * (v - lo) / (hi - lo)     # noqa: E731
        f = T.mono(10)
        p.setFont(f)
        for k in range(5):
            v = lo + (hi - lo) * k / 4
            y = Y(v)
            p.setPen(QPen(QColor("#1b222c"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(T.DIM))
            p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, self.fmt % v if abs(v) < 1e4 else "%.0f" % v)
        if self.zero_line and lo < 0 < hi:
            p.setPen(QPen(QColor("#2f3a4b"), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), Y(0)), QPointF(r.right(), Y(0)))
        if self.xlabels:
            p.setPen(QColor(T.DIM))
            for k in (0, n // 2, n - 1):
                if k < len(self.xlabels):
                    al = Qt.AlignLeft if k == 0 else (Qt.AlignRight if k == n - 1 else Qt.AlignHCenter)
                    box = QRectF(X(k) - (0 if k == 0 else (80 if k == n - 1 else 40)), r.bottom() + 6, 80, 16)
                    p.drawText(box, al | Qt.AlignVCenter, self.xlabels[k])
        for s in self.series:
            vals = s["values"]
            path = QPainterPath()
            started = False
            for i, v in enumerate(vals):
                if v is None:
                    continue
                pt = QPointF(X(i * (n - 1) / max(1, len(vals) - 1)), Y(v))
                if not started:
                    path.moveTo(pt)
                    started = True
                else:
                    path.lineTo(pt)
            pen = QPen(QColor(s["color"]), 2)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        if self._hover is not None:
            i = self._hover
            x = X(i)
            p.setPen(QPen(QColor("#34425a"), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            lines = []
            for s in self.series:
                vals = s["values"]
                j = min(len(vals) - 1, int(round(i * (len(vals) - 1) / max(1, n - 1)))) if len(vals) > 1 else 0
                if j < len(vals) and vals[j] is not None:
                    p.setBrush(QColor(s["color"]))
                    p.setPen(QPen(QColor(T.BG), 2))
                    p.drawEllipse(QPointF(x, Y(vals[j])), 4, 4)
                    lines.append((s["color"], "%s  %s" % (s.get("name", ""), self.fmt % vals[j])))
            if self.xlabels and i < len(self.xlabels):
                lines.insert(0, (T.MUTED, self.xlabels[i]))
            p.setFont(T.mono(11))
            fm = p.fontMetrics()
            w = max(fm.horizontalAdvance(t) for _, t in lines) + 20 if lines else 0
            h = len(lines) * 18 + 10
            bx = x + 12 if x + 12 + w < self.width() else x - 12 - w
            by = max(4, min(self.height() - h - 4, r.top() + 4))
            p.setPen(QPen(QColor(T.BORDER2), 1))
            p.setBrush(QColor(T.CARD))
            p.drawRoundedRect(QRectF(bx, by, w, h), 6, 6)
            for k, (c, t) in enumerate(lines):
                p.setPen(QColor(c))
                p.drawText(QRectF(bx + 10, by + 5 + k * 18, w - 12, 18), Qt.AlignVCenter | Qt.AlignLeft, t)

    def mouseMoveEvent(self, e) -> None:
        n = self._n()
        if n < 2:
            return
        r = self._plot_rect()
        i = int(round((e.position().x() - r.left()) / r.width() * (n - 1)))
        self._hover = max(0, min(n - 1, i)) if r.left() - 10 <= e.position().x() <= r.right() + 10 else None
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = None
        self.update()


class Legend(QWidget):
    def __init__(self, items: Sequence[tuple]):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        for name, color in items:
            dot = QFrame()
            dot.setFixedSize(10, 3)
            dot.setStyleSheet("background: %s; border-radius: 1px;" % color)
            h.addWidget(dot)
            h.addWidget(label(name, "muted"))
            h.addSpacing(4)


def page_header(title: str, pills: Sequence[QWidget] = (), actions: Sequence[QWidget] = ()) -> QFrame:
    f = QFrame()
    f.setObjectName("topbar")
    f.setFixedHeight(56)
    h = QHBoxLayout(f)
    h.setContentsMargins(24, 0, 24, 0)
    h.setSpacing(12)
    h.addWidget(label(title, "h1"))
    for p in pills:
        h.addWidget(p)
    h.addStretch(1)
    for a in actions:
        h.addWidget(a)
    return f


def pill(text: str) -> QLabel:
    return label(text, "pill")


def fmt_r(x: float, d: int = 2) -> str:
    return ("%+." + str(d) + "f") % x


def log_view(height: int = 110, lines: int = 500):
    """Jurnal oynasi (faqat o'qish uchun, mono shrift, chegarasiz)."""
    from PySide6.QtWidgets import QPlainTextEdit
    e = QPlainTextEdit()
    e.setReadOnly(True)
    e.setFont(T.mono(12))
    e.setMaximumBlockCount(lines)
    e.setFixedHeight(height)
    e.setStyleSheet("QPlainTextEdit { border: none; border-top: 1px solid %s; border-radius: 0; background: transparent; color: %s; }"
                    % (T.BORDER, T.MUTED))
    return e
