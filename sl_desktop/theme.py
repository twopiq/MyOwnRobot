"""Ranglar va Qt uslubi. Grafik ranglari dataviz palitrasidan (yorug'/qorong'i rejim uchun alohida tanlangan)."""
from __future__ import annotations

from typing import Dict

LIGHT: Dict[str, str] = {
    "name": "light",
    "page": "#f4f5f7", "surface": "#fcfcfb", "surface2": "#f0f1f3", "hover": "#e8eaee", "border": "#dfe1e6",
    "text": "#0b0b0b", "text2": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
    "accent": "#2a78d6", "accent_text": "#ffffff", "sidebar": "#111827", "sidebar_text": "#cbd5e1",
    # segmentlar (kategorik tartib: 1 ko'k, 2 to'q sariq, 3 dengiz rangi)
    "train": "#2a78d6", "val": "#eb6834", "test": "#1baf7a", "price": "#52514e",
    # ishora (diverging): musbat ko'k, manfiy qizil
    "pos": "#2a78d6", "neg": "#e34948",
    # holat (faqat holat uchun; har doim belgi + yozuv bilan)
    "good": "#0ca30c", "good_text": "#006300", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}

DARK: Dict[str, str] = {
    "name": "dark",
    "page": "#0d0d0d", "surface": "#1a1a19", "surface2": "#232322", "hover": "#2c2c2a", "border": "#333331",
    "text": "#f0efec", "text2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
    "accent": "#3987e5", "accent_text": "#ffffff", "sidebar": "#111111", "sidebar_text": "#c3c2b7",
    "train": "#3987e5", "val": "#d95926", "test": "#199e70", "price": "#c3c2b7",
    "pos": "#3987e5", "neg": "#e66767",
    "good": "#0ca30c", "good_text": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}

FONT = '"Segoe UI", system-ui, -apple-system, "Noto Sans", sans-serif'

_current: Dict[str, str] = DARK


def set_theme(name: str) -> Dict[str, str]:
    global _current
    _current = LIGHT if name == "light" else DARK
    return _current


def c(key: str) -> str:
    return _current[key]


def current() -> Dict[str, str]:
    return _current


def qss(p: Dict[str, str]) -> str:
    return f"""
* {{ font-family: {FONT}; font-size: 13px; color: {p['text']}; }}
QMainWindow, QWidget#page {{ background: {p['page']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame#card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#sidebar {{ background: {p['sidebar']}; border: none; }}
QLabel#h1 {{ font-size: 22px; font-weight: 600; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ color: {p['muted']}; }}
QLabel#text2 {{ color: {p['text2']}; }}
QLabel#kpi {{ font-size: 24px; font-weight: 600; }}
QLabel#brand {{ color: #ffffff; font-size: 16px; font-weight: 700; }}
QLabel#brandsub {{ color: {p['sidebar_text']}; font-size: 11px; }}
QPushButton {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 8px 14px; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:disabled {{ color: {p['muted']}; }}
QPushButton#primary {{ background: {p['accent']}; color: {p['accent_text']}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {p['accent']}; border: 2px solid {p['text2']}; }}
QPushButton#primary:disabled {{ background: {p['hover']}; color: {p['muted']}; }}
QPushButton#danger {{ background: {p['critical']}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#danger:disabled {{ background: {p['hover']}; color: {p['muted']}; }}
QPushButton#nav {{ background: transparent; border: none; border-radius: 8px; color: {p['sidebar_text']};
                   text-align: left; padding: 10px 14px; font-size: 14px; }}
QPushButton#nav:hover {{ background: rgba(255,255,255,0.08); }}
QPushButton#nav:checked {{ background: {p['accent']}; color: #ffffff; font-weight: 600; }}
QPushButton#link {{ background: transparent; border: none; color: {p['accent']}; padding: 2px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {p['accent']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']}; }}
QPlainTextEdit#log {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: {p['surface2']}; border: none; border-radius: 6px; height: 12px; text-align: center;
                color: {p['text2']}; font-size: 11px; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 6px; }}
QSlider::groove:horizontal {{ height: 6px; background: {p['border']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {p['surface']}; border: 2px solid {p['accent']}; width: 14px;
                              margin: -6px 0; border-radius: 9px; }}
QTableWidget {{ background: {p['surface']}; border: none; gridline-color: {p['grid']};
                selection-background-color: {p['hover']}; selection-color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface']}; color: {p['muted']}; border: none;
                        border-bottom: 1px solid {p['border']}; padding: 6px; font-weight: 600; }}
QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {p['muted']}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""
