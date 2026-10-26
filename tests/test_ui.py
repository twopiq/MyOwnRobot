"""Ilova oynasi (offscreen): sahifalar, import, qisqa o'qitish, sozlamalar saqlanishi."""
import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mor.app import MainWindow  # noqa: E402
from mor.db import Database  # noqa: E402
from mor.settings import Settings  # noqa: E402
from mor.ui import theme  # noqa: E402

CSV = os.path.join(os.path.dirname(__file__), "..", "data", "XAUUSD_M15.csv")


def _win(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.STYLE)
    w = MainWindow(Settings(str(tmp_path / "s.json")), Database(tmp_path / "x.db"))
    w.updates.timer.stop()
    return app, w


def test_pages_navigation(tmp_path):
    app, w = _win(tmp_path)
    for key in list(w.pages):
        w.go(key)
        app.processEvents()
    assert {"overview", "data", "training", "memory", "live", "settings"} <= set(w.pages)
    w.close()


def test_settings_persist(tmp_path):
    _, w = _win(tmp_path)
    w.settings.data["lr"] = 0.0007
    w.settings.save()
    w.close()
    assert Settings(str(tmp_path / "s.json")).data["lr"] == 0.0007


def test_import_and_short_training(tmp_path):
    from mor.importers import import_csv
    from mor.trainer import TrainCfg, Trainer
    db = Database(tmp_path / "x.db")
    src = tmp_path / "XAUUSD_M15.csv"
    shutil.copy(CSV, src)
    import_csv(db, str(src), "XAUUSD", "M15", "M15")
    assert db.datasets()
    cfg = TrainCfg(tf="M15", symbols=["XAUUSD"], epochs=1, envs=2, max_seconds=60)
    m = Trainer(db, cfg).run()
    assert "val" in m and "test" in m and "gate_ok" in m
    assert db.latest_policy() is not None


def test_icon_embedded_matches_file():
    with open(os.path.join(os.path.dirname(__file__), "..", "mor", "assets", "icon.svg"), "rb") as f:
        assert f.read().strip() == theme.ICON_SVG.strip()
