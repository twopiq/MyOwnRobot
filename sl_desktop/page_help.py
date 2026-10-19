"""Yordam: robot qanday ishlaydi — infografika va atamalar lug'ati."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from . import theme
from . import widgets as W


class SplitBar(QWidget):
    """Tarix bo'linishi: 60 / 20 / 20 — to'g'ridan-to'g'ri yozuvlar bilan."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(86)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        parts = [("train", 0.6, "O'rganish 60%", "qoidalar shu yerda qidiriladi"),
                 ("val", 0.2, "Validatsiya 20%", "eng yaxshilari saralanadi"),
                 ("test", 0.2, "Holdout 20%", "yakuniy imtihon — tegilmagan")]
        x = 0.0
        f = QFont(self.font())
        for k, frac, name, sub in parts:
            ww = w * frac
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.c(k)))
            p.drawRoundedRect(QRectF(x + 1, 0, ww - 2, 30), 4, 4)
            f.setBold(True)
            f.setPointSizeF(10)
            p.setFont(f)
            p.setPen(QColor(theme.c("text")))
            p.drawText(QRectF(x + 4, 36, ww - 8, 20), Qt.AlignmentFlag.AlignLeft, name)
            f.setBold(False)
            f.setPointSizeF(9)
            p.setFont(f)
            p.setPen(QColor(theme.c("text2")))
            p.drawText(QRectF(x + 4, 56, ww - 8, 30), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, sub)
            x += ww
        p.setPen(QColor(theme.c("text2")))
        f.setPointSizeF(9)
        p.setFont(f)
        p.drawText(QRectF(0, 6, w - 8, 20), Qt.AlignmentFlag.AlignRight, "vaqt →  ")


class HelpPage(W.Page):
    def __init__(self, app):
        super().__init__("Yordam", "Robot qanday ishlaydi va ko'rsatkichlar nimani anglatadi")
        self.app = app
        c = W.Card("Ish jarayoni")
        pipe = W.Pipeline()
        pipe.set(["done", "done", "done", "active"], ["CSV fayl + MT5 dagi so'nggi shamlar", "genetic / optimizer / ml",
                                                       "holdout'da qabul darvozasi", "faqat DEMO hisob, risk % bo'yicha lot"])
        c.body.addWidget(pipe)
        self.lay.addWidget(c)

        c2 = W.Card("Haddan tashqari moslashishdan himoya", "Tarix vaqt bo'yicha bo'linadi; oxirgi 20% qidiruvda umuman ishlatilmaydi")
        c2.body.addWidget(SplitBar())
        self.lay.addWidget(c2)

        steps = W.Card("Boshlash uchun 4 qadam")
        for i, (t, d) in enumerate([
            ("O'rganish", "«O'rganish» sahifasida rejim va tarix faylini tanlab ▶ bosing. MT5 kerak emas."),
            ("Natijani tekshirish", "«Natijalar» sahifasida darvoza shartlari: hammasi ✓ bo'lsa strategiya savdoga tayyor."),
            ("Jonli savdo", "MT5 terminalini oching, DEMO hisobga kiring, «Jonli savdo» sahifasida ▶ bosing."),
            ("Kuzatish", "Bosh sahifada xavf o'lchagichlari va kapital chizig'i. Robot haftada bir o'zi qayta o'rganadi."),
        ], 1):
            row = QHBoxLayout()
            n = W.StatusPill(str(i), "info")
            n.setFixedWidth(26)
            row.addWidget(n)
            row.addWidget(W.label("<b>%s.</b> %s" % (t, d), wrap=True), 1)
            steps.body.addLayout(row)
        self.lay.addWidget(steps)

        g = W.Card("Atamalar")
        for t, d in [
            ("R", "Bitta bitimdagi xavf (kirishdan SL gacha). +1R — xavf qilingan summa miqdorida foyda, −1R — SL."),
            ("Kutilma (exp)", "Bir bitimdan o'rtacha natija, R da. Xarajatlar (spred, sirpanish) ayirilgan."),
            ("Profit faktor (PF)", "Jami foyda / jami zarar. 1.0 dan katta — foydali."),
            ("t-statistika", "Natija tasodif emasligi o'lchovi. ~1 — zaif, ≥2 — ishonchli. Urinishlar ko'p bo'lsa chegara oshadi."),
            ("Holdout", "Tarixning eng yangi 20% qismi. Strategiya uni \"ko'rmagan\" — bu yerda natija haqiqiy imtihon."),
            ("Kill-switch", "Oxirgi N jonli bitim yig'indisi chegaradan past bo'lsa savdo to'xtaydi va robot qayta o'rganadi."),
            ("Walk-forward", "18 oy o'rganish → 3 oy ko'r test; oyna surilib takrorlanadi (optimizer rejimi)."),
        ]:
            g.body.addWidget(W.label("<b>%s</b> — %s" % (t, d), "text2", wrap=True))
        self.lay.addWidget(g)
        self.lay.addWidget(W.Banner("Foyda kafolati yo'q. Robot faqat DEMO hisob uchun mo'ljallangan; real pul bilan "
                                    "ishlatishdan oldin uzoq demo sinovdan o'tkazing.", "warning"))
        self.lay.addStretch(1)

    def refresh(self) -> None:
        self.update()
