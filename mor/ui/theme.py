"""Ko'rinish: ranglar, shrift, ikonkalar (chiziqli SVG) va umumiy uslub jadvali (QSS). Dizayn: Claude Design maketi."""
from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

BG = "#0d1015"
SIDE = "#10141a"
CARD = "#12171e"
BORDER = "#1f2630"
BORDER2 = "#263041"
ROW = "#181e27"
TEXT = "#e7eaef"
MUTED = "#8e99a8"
DIM = "#6b7686"
ACCENT = "#3b82f6"
UP = "#34b27b"
DOWN = "#e5584f"
WARN = "#e0a63b"
SEL = "#1a2230"
HOVER = "#171d26"

MONO = "Cascadia Mono, Consolas, JetBrains Mono, monospace"
SANS = "Segoe UI Variable Text, Segoe UI, Inter, Helvetica Neue, Arial, sans-serif"

PATHS = {
    "overview": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "data": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
    "train": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "memory": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "live": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "settings": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "spread": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    "news": '<path d="M4 4h16v14H8l-4 4V4z"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><path d="M20.5 15a9 9 0 1 1-2.1-9.4L23 10"/>',
}


def svg(name: str, color: str = MUTED, size: int = 18, stroke: float = 1.6) -> QPixmap:
    src = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="%s" '
           'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, stroke, PATHS[name]))
    return render_svg(src.encode(), size)


def render_svg(data: bytes, size: int) -> QPixmap:
    scale = 2
    r = QSvgRenderer(QByteArray(data))
    img = QImage(size * scale, size * scale, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = MUTED, size: int = 18) -> QIcon:
    return QIcon(svg(name, color, size))


ICON_SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="8" y="8" width="240" height="240" rx="56" fill="#121821"/><rect x="8.5" y="8.5" width="239" height="239" rx="55.5" fill="none" stroke="#2a3443"/><path d="M56 176 L104 112 L140 148 L196 72" fill="none" stroke="#3b82f6" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/><circle cx="196" cy="72" r="14" fill="#e7eaef"/><circle cx="56" cy="176" r="8" fill="#3b82f6"/></svg>'''   # mor/assets/icon.svg bilan bir xil (zip ichida fayl yo'q, shuning uchun kodda)


def app_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(render_svg(ICON_SVG, sz))
    return ic


def mono(size: int = 12, weight: int = 500) -> QFont:
    f = QFont()
    f.setFamilies([s.strip() for s in MONO.split(",")])
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    f.setStyleHint(QFont.Monospace)
    return f


def tone_color(tone: str) -> str:
    return {"up": UP, "down": DOWN, "warn": WARN, "accent": ACCENT, "muted": MUTED}.get(tone, TEXT)


STYLE = f"""
* {{ font-family: {SANS}; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER2}; padding: 4px 6px; }}
QFrame#side {{ background: {SIDE}; border-right: 1px solid {BORDER}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#cardHead {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QLabel {{ background: transparent; border: none; }}
QFrame#row {{ background: transparent; border: none; border-bottom: 1px solid {ROW}; border-radius: 0; }}
QLabel[role="h1"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="b"] {{ font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="dim"] {{ color: {DIM}; font-size: 12px; }}
QLabel[role="num"] {{ font-size: 22px; font-weight: 500; }}
QLabel[role="pill"] {{ border: 1px solid {BORDER2}; border-radius: 12px; padding: 3px 10px; color: #aab4c2; font-size: 12px; }}
QLabel[role="tag"] {{ background: #17202d; color: #8fb3ee; border-radius: 4px; padding: 2px 6px; font-size: 11px; font-weight: 600; }}
QLabel[role="tag"][tone="up"] {{ background: #13261e; color: #5fcf9d; }}
QLabel[role="tag"][tone="down"] {{ background: #2a1517; color: #e8736b; }}
QLabel[role="tag"][tone="warn"] {{ background: #2a2312; color: #d9b155; }}
QPushButton {{ background: #151b24; border: 1px solid #2a3443; border-radius: 6px; padding: 0 14px; height: 32px; font-weight: 500; }}
QPushButton:hover {{ background: #1a212c; border-color: #34425a; }}
QPushButton:disabled {{ color: {DIM}; background: #12171e; border-color: {BORDER}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton[kind="primary"]:hover {{ background: #4b8ff7; }}
QPushButton[kind="primary"]:disabled {{ background: #1d2a40; border-color: #1d2a40; color: #6c82a6; }}
QPushButton[kind="danger"] {{ border-color: #5a2a2d; color: #f0807a; }}
QPushButton[kind="chip"] {{ height: 26px; border-radius: 13px; padding: 0 12px; background: transparent; border: 1px solid {BORDER2}; color: {MUTED}; font-size: 12px; }}
QPushButton[kind="chip"]:checked {{ background: {SEL}; border-color: #34425a; color: white; }}
QPushButton#nav {{ text-align: left; height: 36px; padding: 0 10px; border: none; border-radius: 6px; background: transparent; color: {MUTED}; font-weight: 500; }}
QPushButton#nav:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SEL}; color: white; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QPlainTextEdit {{ background: #0f1319; border: 1px solid #2a3443; border-radius: 6px; padding: 5px 8px; min-height: 20px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER2}; selection-background-color: {SEL}; outline: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #34425a; background: #0f1319; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTableWidget, QListWidget {{ background: transparent; border: none; outline: 0; gridline-color: transparent; selection-background-color: {SEL}; selection-color: {TEXT}; }}
QTableWidget::item {{ border-bottom: 1px solid {ROW}; padding: 0 10px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {DIM}; border: none; border-bottom: 1px solid {BORDER}; padding: 8px 10px; font-size: 11px; font-weight: 500; text-align: left; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #263041; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #263041; border-radius: 5px; min-width: 24px; }}
QProgressBar {{ background: #1b222c; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER2}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SEL}; }}
"""
