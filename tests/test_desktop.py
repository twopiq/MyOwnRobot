"""Desktop ilova uchun: robot hisobot/holat fayllari (Qt'siz) va oynaning tutun testi (PySide6 bo'lsa)."""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sl_core as sc  # noqa: E402
from test_selflearn import make_fake, synth  # noqa: E402


def test_gate_checks_agree_with_gate():
    cfg = sc.Cfg()
    seg = {"test": {"n": 50, "exp": 0.08, "pf": 1.2, "t": 0.7}, "val": {"exp": 0.1}, "train": {"exp": -0.01}}
    rep = sc.Report(mode="genetic")
    ok, why = sc.gate(cfg, seg, [0.1, -0.1, 0.2, 0.3], rep=rep)
    failed = {c["key"] for c in rep.checks if not c["ok"]}
    assert not ok and failed == {"t", "train"} and len(why) == 2
    assert all({"label", "value", "need", "ok"} <= set(c) for c in rep.checks)


def test_curves_of_is_sorted_and_timestamped():
    idx = pd.date_range("2024-01-01", periods=10, freq="15min")
    t = sc.Trades(np.array([5, 2]), np.array([6, 3]), np.array([1, -1]), np.array([1.0, -1.0]), np.array([1.0, -1.0]))
    c = sc.curves_of({"test": t, "val": sc.Trades.empty()}, idx)
    assert list(c) == ["test"] and c["test"]["r"] == [-1.0, 1.0] and c["test"]["d"] == [-1, 1]
    assert c["test"]["t"][0] == int(idx[2].timestamp())


def test_cli_learn_writes_report_and_progress(tmp_path):
    hp = tmp_path / "h.csv"
    synth(60_000).to_csv(hp, index_label="time")
    env = {**os.environ, "SL_PROGRESS": "1", "SL_REQUIRE_PASS": "0"}
    out = subprocess.run([sys.executable, str(SL_DIR / "selflearn_robot.py"), "--learn", "--mode", "genetic", "--history", str(hp),
                          "--budget", "15", "--state", str(tmp_path / "st")], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr[-800:]
    prog = [json.loads(x[len("@@PROGRESS "):]) for x in out.stdout.splitlines() if x.startswith("@@PROGRESS ")]
    assert prog and prog[0]["attempt"] == 1 and len(prog[0]["args"]) == 3
    rep = json.loads((tmp_path / "st" / "report_genetic.json").read_text(encoding="utf-8"))
    assert rep["mode"] == "genetic" and rep["bars"] == 60_000 and set(rep["bounds"]) == {"train", "val", "test"}
    if rep["segments"].get("test"):
        assert rep["checks"] and rep["curves"]["test"]["r"]
        assert len(rep["curves"]["test"]["r"]) == rep["segments"]["test"]["n"]


def test_write_status_reports_account_and_positions(tmp_path):
    import selflearn_robot as sr
    m = make_fake(balance=5000.0)
    m.positions_get = lambda symbol=None: [types.SimpleNamespace(ticket=11, type=0, volume=0.1, price_open=2000.0, sl=1990.0,
                                                                 tp=2020.0, profit=12.5, time=1, magic=sc.Cfg().magic)]
    cfg = sc.Cfg(state_dir=str(tmp_path))
    br = sc.Broker(cfg, m)
    st = sr.LiveState(cfg)
    st.rs = [1.0, -1.0, 0.5]
    eng = types.SimpleNamespace(ready=lambda: True, validated=True, describe=lambda: "BUY: rsi14 < 30 | SL 1×ATR")
    sr.write_status(cfg, br, eng, st, sr.Learner(cfg), 4900.0)
    d = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert d["balance"] == 5000.0 and d["day_equity"] == 4900.0 and d["rs"] == [1.0, -1.0, 0.5]
    assert d["positions"][0]["dir"] == 1 and d["positions"][0]["profit"] == 12.5 and d["spread"] == pytest.approx(0.3)
    assert d["ready"] and d["validated"] and not d["learning"]


def test_settings_env_maps_fields(tmp_path):
    from sl_desktop.settings import Settings
    s = Settings(tmp_path / "s.json", state=tmp_path / "st")
    s.set("SL_DEMO_ONLY", False)
    s.set("SL_RISK_PCT", 1.25)
    s.set("SL_LOGIN", 0)
    s.save()
    e = Settings(tmp_path / "s.json", state=tmp_path / "st").env()
    assert e["SL_DEMO_ONLY"] == "0" and e["SL_RISK_PCT"] == "1.25" and "SL_LOGIN" not in e
    assert e["SL_STATE_DIR"] == str(tmp_path / "st") and e["SL_PROGRESS"] == "1"
    assert Path(e["SL_HISTORY"]).name == "XAUUSD_M15.csv"


def test_window_renders_all_pages(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("matplotlib")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    from sl_desktop import data as D
    st = tmp_path / "st"
    st.mkdir()
    # haqiqiy dvigateldan hisobot
    import sl_genetic
    cfg = sc.Cfg(mode="genetic", state_dir=str(st), budget_sec=8, require_pass=False)
    h = synth(40_000)
    rep = sl_genetic.Engine(cfg).learn(h)
    sc.append_learn_log(cfg, rep)
    sc.save_report(cfg, rep, h)
    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(tmp_path / "s.json", state=st))
    for k in w.pages:
        w.go(k)
    assert w.pages["results"].content.isVisibleTo(w.pages["results"])
    assert D.monthly_r(D.latest_report(st)).shape[0] > 0
    w.pages["live"].rchart.show([1.0, -1.0, -1.0, 2.0], -6.0, 20)
    w.apply_theme("light")
    w.apply_theme("dark")
    state, tone = w.robot_state(None)
    assert tone == "idle"
    w.close()


def test_robot_output_survives_cp1252_console(tmp_path):
    """Windows konsoli (cp1252) "≥" ni chiqara olmaydi — robot baribir UTF-8 da yozishi kerak (ML strategiya matni)."""
    hp = tmp_path / "h.csv"
    synth(40_000).to_csv(hp, index_label="time")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "SL_REQUIRE_PASS": "0"}
    out = subprocess.run([sys.executable, str(SL_DIR / "selflearn_robot.py"), "--learn", "--mode", "ml", "--history", str(hp),
                          "--state", str(tmp_path / "st")], capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[-1500:]
    assert "≥" in out.stdout.decode("utf-8")


def test_error_panel_copies_full_report(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(tmp_path / "s.json", state=tmp_path / "st"))
    lp = w.pages["learn"]
    lp.log.appendPlainText("10:00:00 O'RGANISH boshlandi\nUnicodeEncodeError: 'charmap' codec can't encode character '\\u2265'")
    lp._on_finished(1, "UnicodeEncodeError: 'charmap' codec can't encode character '\\u2265'")
    assert lp.error.isVisibleTo(lp) and "💡" in lp.error.text.text()
    lp.error.copy()
    clip = QApplication.clipboard().text()
    assert "Chiqish kodi: 1" in clip and "O'RGANISH boshlandi" in clip and "SL_MODE=" in clip
    w.close()


def test_learn_page_shows_attempts_in_forever_mode(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(tmp_path / "s.json", state=tmp_path / "st"))
    lp = w.pages["learn"]
    assert lp.forever.isChecked() and not lp.repeat.isEnabled()
    lp._reset_progress()
    for i, (t, ok) in enumerate([(0.4, False), (1.2, False), (2.3, True)], 1):
        lp._on_attempt({"no": i, "ok": ok, "t": t, "exp": 0.02 * i, "n": 80, "need_t": 1.0 + 0.3 * i})
    assert lp.achart.isVisibleTo(lp) and "Urinish 3" in lp.step_lbl.text() and "2.30" in lp.step_lbl.text()
    (tmp_path / "st").mkdir(exist_ok=True)
    (tmp_path / "st" / "attempts.json").write_text(json.dumps({"genetic|XAUUSD|M15|2022-01-03 00:00:00|2026-W42": 4}))
    lp._budget_changed()
    assert lp.attempts_done() == 4 and "4 urinish" in lp.done_lbl.text()
    w.close()


def test_settings_live_in_stable_user_dir_and_migrate_from_app_dir(tmp_path, monkeypatch):
    from sl_desktop import settings as S
    old, new = tmp_path / "app_v1", tmp_path / "userdata"
    (old / "state").mkdir(parents=True)
    (old / "state" / "optimizer_strategy.json").write_text("{}")
    (old / "desktop_settings.json").write_text('{"env": {"SL_MODE": "ml", "SL_TERMINAL": "E:/MT5/terminal64.exe", "SL_LOGIN": 5}}')
    monkeypatch.setattr(S, "app_dir", lambda: old)
    monkeypatch.setenv("MYOWNROBOT_DATA_DIR", str(new))
    s = S.Settings()
    assert s.path == new / "desktop_settings.json"
    assert s.get("SL_MODE") == "ml" and s.get("SL_TERMINAL") == "E:/MT5/terminal64.exe" and s.get("SL_LOGIN") == 5
    assert (new / "state" / "optimizer_strategy.json").exists()
    s.set("SL_SERVER", "X-Demo")
    s.save()
    # ilova boshqa papkaga ko'chdi (yangi zip/yangilanish): sozlamalar yo'qolmaydi
    monkeypatch.setattr(S, "app_dir", lambda: tmp_path / "app_v2")
    s2 = S.Settings()
    assert s2.get("SL_MODE") == "ml" and s2.get("SL_SERVER") == "X-Demo" and s2.state_dir() == new / "state"


def test_live_page_saves_fields_immediately_and_restores_mode(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("matplotlib")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    QApplication.instance() or QApplication([])
    path = tmp_path / "s.json"
    w = MainWindow(Settings(path, state=tmp_path / "st"))
    live = w.pages["live"]
    live.mode.setCurrentIndex(live.mode.findData("ml"))
    live.terminal.setText("E:/MT5/terminal64.exe")
    live.terminal.editingFinished.emit()
    live.password.setText("pw")
    live.password.editingFinished.emit()
    live.server.setText("MetaQuotes-Demo")
    live.server.editingFinished.emit()
    saved = json.loads(path.read_text(encoding="utf-8"))["env"]
    assert saved["SL_MODE"] == "ml" and saved["SL_TERMINAL"] == "E:/MT5/terminal64.exe"
    assert saved["SL_PASSWORD"] == "pw" and saved["SL_SERVER"] == "MetaQuotes-Demo"
    w2 = MainWindow(Settings(path, state=tmp_path / "st"))        # qayta ochish
    l2 = w2.pages["live"]
    assert l2.mode.currentData() == "ml" and l2.terminal.text() == "E:/MT5/terminal64.exe" and l2.server.text() == "MetaQuotes-Demo"


def test_chart_tooltip_stays_inside_figure_at_every_corner(monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("matplotlib")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from sl_desktop.charts import AttemptsChart
    QApplication.instance() or QApplication([])
    c = AttemptsChart()
    c.resize(620, 230)
    rows = [{"no": i + 1, "t": t, "ok": False, "exp": 0.1, "need_t": 2.15} for i, t in enumerate([2.9, 0.1, -3.4, 2.8, 1.5])]
    c.show(rows)
    c.draw()
    for i in range(len(rows)):                             # yuqori/pastki/chap/o'ng chekka nuqtalari
        xs, ys = c._hover[0][0][i], c._hover[0][1][i]
        px, py = c.ax.transData.transform((xs, ys))
        class E:                                           # sichqoncha shu nuqta ustida
            inaxes, xdata, x, y = c.ax, xs, px, py
        c._on_move(E)
        bb = c._tip.get_window_extent(c.get_renderer())
        assert bb.x0 >= -1 and bb.y0 >= -1 and bb.x1 <= c.fig.bbox.width + 1 and bb.y1 <= c.fig.bbox.height + 1, (i, bb)
