"""Qayta ishlatiladigan UI bloklari: karta, KPI plitka, holat belgisi, o'lchagich, jarayon zanjiri, darvoza ro'yxati."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme

STATUS_ICON = {"good": "✓", "warning": "!", "serious": "!", "critical": "✕", "idle": "•", "info": "i", "busy": "⟳"}


def label(text: str = "", obj: str = "", wrap: bool = False, plain: bool = False) -> QLabel:
    """plain=True — matn HTML sifatida talqin qilinmaydi (strategiya va sabablarda "<" bor)."""
    lb = QLabel(text)
    if plain:
        lb.setTextFormat(Qt.TextFormat.PlainText)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def clear_layout(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


class Card(QFrame):
    """Sarlavhali oq/qora karta. body — ichki vertikal joylashuv."""

    def __init__(self, title: str = "", subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        if title:
            head = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(2)
            self.title = label(title, "h2")
            col.addWidget(self.title)
            if subtitle:
                self.subtitle = label(subtitle, "muted", wrap=True)
                col.addWidget(self.subtitle)
            head.addLayout(col, 1)
            self.actions = QHBoxLayout()
            head.addLayout(self.actions)
            lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        lay.addLayout(self.body, 1)


class KpiTile(QFrame):
    """Katta raqam + izoh. Rang faqat kichik belgida (matn har doim asosiy rangda)."""

    def __init__(self, title: str, value: str = "—", sub: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(170)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        self.t = label(title, "muted")
        self.v = label(value, "kpi")
        self.s = label(sub, "text2", wrap=True)
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.s)
        lay.addStretch(1)

    def set(self, value: str, sub: Optional[str] = None, tone: Optional[str] = None) -> None:
        self.v.setText(value)
        if sub is not None:
            if tone in ("good", "critical", "warning", "serious"):
                sub = '<span style="color:%s">%s</span> %s' % (theme.c("good_text" if tone == "good" else tone),
                                                               "▲" if tone == "good" else "▼" if tone == "critical" else "!", sub)
            self.s.setText(sub)


class StatusPill(QWidget):
    """Holat: rangli doira ichida belgi + yozuv (rang yolg'iz o'zi ma'no tashimaydi)."""

    def __init__(self, text: str = "", tone: str = "idle", big: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.text, self.tone, self.big = text, tone, big
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set(self, text: str, tone: str) -> None:
        self.text, self.tone = text, tone
        self.updateGeometry()
        self.update()

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(13 if self.big else 9.5)
        f.setBold(True)
        return f

    def sizeHint(self) -> QSize:
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        h = 36 if self.big else 26
        return QSize(fm.horizontalAdvance(self.text) + h + 22, h)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        col = QColor(theme.c(self.tone) if self.tone in ("good", "warning", "serious", "critical") else
                     theme.c("accent") if self.tone in ("info", "busy") else theme.c("muted"))
        bg = QColor(col)
        bg.setAlpha(36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        d = h - 10
        p.setBrush(col)
        p.drawEllipse(QRectF(5, 5, d, d))
        f = self._font()
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(5, 5, d, d), Qt.AlignmentFlag.AlignCenter, STATUS_ICON.get(self.tone, "•"))
        p.setPen(QColor(theme.c("text")))
        p.drawText(QRectF(d + 14, 0, self.width() - d - 14, h), Qt.AlignmentFlag.AlignVCenter, self.text)


class Gauge(QWidget):
    """Yarim doira o'lchagich: qiymat chegaraga qanchalik yaqinligini ko'rsatadi (0..1)."""

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.title = title
        self.frac, self.value_text, self.sub = 0.0, "—", ""
        self.setMinimumSize(180, 140)

    def set(self, frac: float, value_text: str, sub: str = "") -> None:
        self.frac = max(0.0, min(1.0, frac))
        self.value_text, self.sub = value_text, sub
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w - 20, (h - 46) * 2)
        r = QRectF((w - side) / 2, 26, side, side)
        pen = QPen(QColor(theme.c("grid")), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 180 * 16, -180 * 16)
        tone = "good" if self.frac < 0.5 else "warning" if self.frac < 0.8 else "critical"
        pen.setColor(QColor(theme.c(tone)))
        p.setPen(pen)
        if self.frac > 0:
            p.drawArc(r, 180 * 16, int(-180 * 16 * self.frac))
        p.setPen(QColor(theme.c("muted")))
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.drawText(QRectF(0, 0, w, 20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.title)
        f.setPointSizeF(16)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.c("text")))
        cy = r.center().y()
        p.drawText(QRectF(0, cy - 30, w, 30), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.value_text)
        f.setPointSizeF(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(theme.c("text2")))
        p.drawText(QRectF(0, cy + 2, w, 20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.sub)


class Pipeline(QWidget):
    """Tarix → O'rganish → Tekshiruv → Savdo zanjiri; har bosqich: done / active / fail / todo."""

    STEPS = [("Tarix", "📊"), ("O'rganish", "🧠"), ("Tekshiruv", "🛡"), ("Savdo", "💹")]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.states = ["todo"] * 4
        self.notes = [""] * 4
        self.setMinimumHeight(110)

    def set(self, states: Sequence[str], notes: Sequence[str]) -> None:
        self.states, self.notes = list(states), list(notes)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.STEPS)
        w = self.width()
        seg = w / n
        cy, rad = 32, 22
        tones = {"done": theme.c("good"), "active": theme.c("accent"), "fail": theme.c("critical"),
                 "warn": theme.c("warning"), "todo": theme.c("grid")}
        for i in range(n - 1):
            x1, x2 = seg * (i + 0.5) + rad + 6, seg * (i + 1.5) - rad - 6
            pen = QPen(QColor(tones["done"] if self.states[i] == "done" else theme.c("grid")), 3)
            if self.states[i] != "done":
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(int(x1), cy, int(x2), cy)
        for i, (name, icon) in enumerate(self.STEPS):
            st = self.states[i]
            cx = seg * (i + 0.5)
            col = QColor(tones.get(st, tones["todo"]))
            fill = QColor(col)
            fill.setAlpha(40 if st == "todo" else 60)
            p.setPen(QPen(col, 3))
            p.setBrush(fill)
            p.drawEllipse(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad))
            f = QFont(self.font())
            f.setPointSizeF(14)
            p.setFont(f)
            mark = {"done": "✓", "fail": "✕", "warn": "!"}.get(st, icon)
            p.setPen(QColor(theme.c("text")))
            p.drawText(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), Qt.AlignmentFlag.AlignCenter, mark)
            f.setPointSizeF(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(cx - seg / 2, cy + rad + 6, seg, 18), Qt.AlignmentFlag.AlignHCenter, name)
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(theme.c("text2")))
            p.drawText(QRectF(cx - seg / 2 + 4, cy + rad + 24, seg - 8, 30),
                       Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self.notes[i] if i < len(self.notes) else "")


class CheckRow(QWidget):
    """Darvoza sharti: belgi, nom, qiymat/chegara va chegaraga nisbatan gorizontal chiziq."""

    def __init__(self, chk: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.chk = chk
        self.setMinimumHeight(40)
        self.setToolTip(HELP.get(chk.get("key", ""), ""))

    def paintEvent(self, _e) -> None:
        c = self.chk
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ok = c.get("ok")
        col = QColor(theme.c("good" if ok else "critical"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(0, h / 2 - 10, 20, 20))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, h / 2 - 10, 20, 20), Qt.AlignmentFlag.AlignCenter, "✓" if ok else "✕")
        p.setPen(QColor(theme.c("text")))
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(30, 0, w * 0.42, h), Qt.AlignmentFlag.AlignVCenter, c.get("label", ""))
        v, need = float(c.get("value", 0)), float(c.get("need", 0))
        fmt = "%d" if c.get("key") == "n" else "%.0f%%" if c.get("key") == "chunks" else "%.2f"
        mul = 100 if c.get("key") == "chunks" else 1
        txt = (fmt % (v * mul)) + "  /  " + c.get("op", "≥").replace(">=", "≥") + " " + (fmt % (need * mul))
        p.setPen(QColor(theme.c("text2")))
        p.drawText(QRectF(w * 0.42 + 30, 0, w * 0.25, h), Qt.AlignmentFlag.AlignVCenter, txt)
        # chiziq: chegara — o'rtadagi belgi; qiymat chegaraga nisbatan
        x0, bw = w * 0.70, w * 0.30 - 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.c("grid")))
        p.drawRoundedRect(QRectF(x0, h / 2 - 4, bw, 8), 4, 4)
        scale = max(abs(need) * 2, abs(v) * 1.1, 1e-6)
        frac = max(0.0, min(1.0, (v - (need - scale / 2)) / scale))
        p.setBrush(col)
        p.drawRoundedRect(QRectF(x0, h / 2 - 4, max(8, bw * frac), 8), 4, 4)
        p.setPen(QPen(QColor(theme.c("text")), 2))
        p.drawLine(int(x0 + bw / 2), int(h / 2 - 9), int(x0 + bw / 2), int(h / 2 + 9))


HELP = {
    "n": "Tegilmagan oxirgi davrda (holdout) yetarli bitim bo'lishi — kam bitimdagi natija tasodif bo'lishi mumkin.",
    "exp": "Bir bitimdan o'rtacha natija, xatar birligida (R). +0.05R = har bitimda xavfning 5% foyda.",
    "pf": "Profit faktor: jami foyda / jami zarar. 1.0 dan katta — foydali.",
    "t": "t-statistika: natija tasodif emasligi ishonchi. Urinishlar ko'p bo'lsa chegara oshadi.",
    "val": "Validatsiya davrida ham foydali bo'lishi kerak.",
    "train": "O'rganish davrida foydali bo'lishi kerak.",
    "chunks": "Holdout 4 bo'lakka bo'linadi; kamida yarmi foydali bo'lishi kerak (barqarorlik).",
}


class GateList(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)

    def set(self, checks: List[Dict[str, Any]]) -> None:
        clear_layout(self.lay)
        if not checks:
            self.lay.addWidget(label("Darvoza shartlari hali hisoblanmagan (strategiya validatsiyadan o'tmadi).", "muted",
                                     wrap=True))
            return
        for c in checks:
            self.lay.addWidget(CheckRow(c))


class ModeCard(QPushButton):
    """Rejim tanlash kartasi (radio kabi)."""

    def __init__(self, key: str, title: str, icon: str, desc: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        ic = label(icon)
        ic.setStyleSheet("font-size: 26px; background: transparent;")
        top.addWidget(ic)
        top.addStretch(1)
        self.tick = label("")
        self.tick.setStyleSheet("background: transparent; font-weight: 700;")
        top.addWidget(self.tick)
        lay.addLayout(top)
        t = label(title, "h2")
        t.setStyleSheet("background: transparent;")
        lay.addWidget(t)
        d = label(desc, "text2", wrap=True)
        d.setStyleSheet("background: transparent; font-size: 12px;")
        lay.addWidget(d, 1)
        for w in (ic, t, d, self.tick):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._style)
        self._style(False)

    def _style(self, on: bool) -> None:
        p = theme.current()
        self.tick.setText("✓ Tanlangan" if on else "")
        self.tick.setStyleSheet("background: transparent; font-weight: 700; color: %s;" % p["accent"])
        self.setStyleSheet("QPushButton { background: %s; border: %s; border-radius: 12px; text-align: left; }"
                           "QPushButton:hover { border: 2px solid %s; }" % (
                               p["surface"], ("2px solid " + p["accent"]) if on else ("1px solid " + p["border"]), p["accent"]))


class Banner(QFrame):
    """Ogohlantirish / ma'lumot satri."""

    def __init__(self, text: str = "", tone: str = "info", parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.pill = StatusPill("", tone)
        self.pill.setFixedWidth(26)
        lay.addWidget(self.pill)
        self.text = label(text, wrap=True)
        lay.addWidget(self.text, 1)
        self.set(text, tone)

    def set(self, text: str, tone: str = "info") -> None:
        self.text.setText(text)
        self.pill.set("", tone)
        col = theme.c(tone) if tone in ("good", "warning", "serious", "critical") else theme.c("accent")
        self.setStyleSheet("Banner { background: %s; border: 1px solid %s; border-radius: 10px; }" % (
            _alpha(col, 0.10), _alpha(col, 0.45)))
        self.setVisible(bool(text))


def _alpha(hexcol: str, a: float) -> str:
    q = QColor(hexcol)
    return "rgba(%d,%d,%d,%.2f)" % (q.red(), q.green(), q.blue(), a)


class Legend(QWidget):
    """Grafik ustidagi legenda: rangli belgi + matn (matn rangi — asosiy)."""

    def __init__(self, items: Sequence[tuple] = (), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(16)
        self.set(items)

    def set(self, items: Sequence[tuple]) -> None:
        clear_layout(self.lay)
        for name, col, *kind in items:
            sw = QLabel()
            shape = kind[0] if kind else "box"
            sw.setFixedSize(14, 4 if shape == "line" else 12)
            sw.setStyleSheet("background: %s; border-radius: 2px;" % col)
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(sw)
            row.addWidget(label(name, "text2"))
            self.lay.addLayout(row)
        self.lay.addStretch(1)


def grid(widgets: Sequence[QWidget], cols: int) -> QGridLayout:
    g = QGridLayout()
    g.setSpacing(12)
    for i, w in enumerate(widgets):
        g.addWidget(w, i // cols, i % cols)
    return g


class Page(QWidget):
    """Sahifa: sarlavha + o'ng tomonda amal tugmalari + aylantiriladigan tarkib."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("page")
        from PySide6.QtWidgets import QScrollArea
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(sc)
        inner = QWidget()
        inner.setObjectName("page")
        sc.setWidget(inner)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(28, 24, 28, 28)
        self.lay.setSpacing(16)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label(title, "h1"))
        if subtitle:
            col.addWidget(label(subtitle, "muted", wrap=True))
        head.addLayout(col, 1)
        self.head_right = QHBoxLayout()
        self.head_right.setSpacing(8)
        head.addLayout(self.head_right)
        self.lay.addLayout(head)

    def refresh(self) -> None:
        """Ma'lumot yoki mavzu o'zgarganda qayta chizish."""
