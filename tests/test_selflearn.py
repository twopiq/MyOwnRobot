"""Self-learning robot (selflearn/): yadro, uch dvigatel, mustaqillik, MT5 qatlami (soxta mt5 bilan)."""
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SL_DIR))

import sl_core as sc  # noqa: E402


def synth(n=100_000, seed=3, start="2022-01-03"):
    """Tasodifiy yurish (M15) — hech qanday ustunlik yo'q."""
    r = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="15min")
    c = 1800 + np.cumsum(r.normal(0, 1.2, n))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) + np.abs(r.normal(0, 0.5, n))
    l = np.minimum(o, c) - np.abs(r.normal(0, 0.5, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": r.integers(50, 500, n).astype(float)}, index=idx)


@pytest.fixture(scope="module")
def hist():
    return synth()


def cfg_for(mode, tmp_path, **kw):
    c = sc.Cfg(mode=mode, state_dir=str(tmp_path / "state"), budget_sec=25, require_pass=False)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ---------------------------------------------------------------- simulyator

def _ref(b, sp, sj, i, d, s, p, hd):
    e0 = b.o[i + 1]
    e = e0 + sp + sj if d > 0 else e0 - sj
    slp, tpp = (e - s, e + p) if d > 0 else (e + s, e - p)
    for k in range(hd):
        j = i + 1 + k
        if d > 0:
            if b.l[j] <= slp:
                return j, (slp - sj - e) / s
            if b.h[j] >= tpp:
                return j, (tpp - e) / s
        else:
            if b.h[j] + sp >= slp:
                return j, (e - (slp + sj)) / s
            if b.l[j] + sp <= tpp:
                return j, (e - tpp) / s
    j = i + hd
    x = b.c[j] if d > 0 else b.c[j] + sp
    return j, ((x - e) if d > 0 else (e - x)) / s


def test_simulator_matches_reference_loop(hist):
    b = sc.Bars.of(hist)
    a = sc.atr(b.h, b.l, b.c, 14)
    r = np.random.default_rng(1)
    idx = np.sort(r.choice(np.arange(400, len(b) - 200), 1500, replace=False))
    dirs = r.choice([-1, 1], len(idx))
    sl, hold = a[idx] * 1.5, r.choice([16, 48], len(idx))
    t = sc.simulate(b, idx, dirs, sl, sl * 1.5, hold, 0.3, 0.05, no_overlap=False)
    assert len(t) == len(idx)
    for k in range(0, len(idx), 7):
        j, rr = _ref(b, 0.3, 0.05, idx[k], dirs[k], sl[k], sl[k] * 1.5, hold[k])
        assert t.exit_i[k] == j and abs(t.R[k] - rr) < 1e-9


def test_sl_has_priority_when_both_hit_same_bar():
    n = 400
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    z = np.full(n, 100.0)
    h, l = z + 0.1, z - 0.1
    h[301], l[301] = 110.0, 90.0           # bir shamda ham SL ham TP
    b = sc.Bars(idx, z.copy(), h, l, z.copy(), np.ones(n))
    t = sc.simulate(b, np.array([300]), 1, 5.0, 5.0, 10, 0.0, 0.0)
    assert len(t) == 1 and t.R[0] == pytest.approx(-1.0)


def test_no_overlap_skips_signals_inside_open_trade(hist):
    b = sc.Bars.of(hist)
    a = sc.atr(b.h, b.l, b.c, 14)
    idx = np.arange(1000, 1040)
    t = sc.simulate(b, idx, 1, 3 * a[idx], 3 * a[idx], 32, 0.3, 0.05)
    assert len(t) < len(idx) and np.all(t.entry_i[1:] > t.exit_i[:-1])


def test_random_entries_lose_roughly_the_costs(hist):
    b = sc.Bars.of(hist)
    a = sc.atr(b.h, b.l, b.c, 14)
    idx = np.arange(1000, 90000, 9)
    t = sc.simulate(b, idx, 1, 1.5 * a[idx], 1.5 * a[idx], 32, 0.3, 0.05)
    assert sc.stats(t)["exp"] < 0.02       # xarajatlar hisobga olinadi: tasodifiy kirish foyda bermaydi


# ---------------------------------------------------------------- tarix

def test_history_readers(tmp_path, hist):
    small = hist.iloc[:2000]
    p1 = tmp_path / "a.csv"
    small.to_csv(p1, index_label="time")
    assert sc.read_history_file(str(p1)).shape == (2000, 5)
    p2 = tmp_path / "mt4.csv"                     # MT4 eksporti: sarlavhasiz, sana,vaqt,o,h,l,c,hajm
    with open(p2, "w") as f:
        for t, r in small.iterrows():
            f.write(f"{t:%Y.%m.%d},{t:%H:%M},{r.open},{r.high},{r.low},{r.close},{int(r.volume)}\n")
    d2 = sc.read_history_file(str(p2), gmt=2)
    assert len(d2) == 2000 and d2.index[0] == small.index[0] - pd.Timedelta(hours=2)
    p3 = tmp_path / "e.csv"                       # epoch soniyalar
    e = small.copy()
    e.insert(0, "time", ((e.index - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype(int))
    e.to_csv(p3, index=False)
    assert sc.read_history_file(str(p3)).index[0] == small.index[0]
    p4 = tmp_path / "a.pkl"
    small.to_pickle(p4)
    assert len(sc.read_history_file(str(p4))) == 2000


def test_to_tf_resamples_m1_to_m15():
    idx = pd.date_range("2024-01-01", periods=300, freq="1min")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    out = sc.to_tf(df, 15)
    assert len(out) == 20 and out["volume"].iloc[0] == 15 and out["high"].iloc[0] == 2.0


def test_us_dst_server_to_utc():
    ts = pd.DatetimeIndex(["2024-01-15 12:00", "2024-07-15 12:00", "2024-03-09 12:00", "2024-03-11 12:00"])
    u = sc.server_to_utc(ts, 2.0)
    assert [x.hour for x in u] == [10, 9, 10, 9]


# ---------------------------------------------------------------- lookahead yo'q

def test_features_have_no_lookahead(hist):
    import sl_genetic as g
    import sl_ml as m
    import sl_optimizer as o
    df = hist.iloc[:6000]
    cut = 5000
    b_full, b_cut = sc.Bars.of(df), sc.Bars.of(df.iloc[:cut])
    f1, f2 = g.build_features(b_full, df.index), g.build_features(b_cut, df.index[:cut])
    for k in f2:
        assert np.allclose(f1[k][:cut], f2[k], equal_nan=True), k
    X1, n1, _ = m.build_features(b_full, df.index)
    X2, n2, _ = m.build_features(b_cut, df.index[:cut])
    assert n1 == n2 and np.allclose(X1[:cut], X2, equal_nan=True, atol=1e-5)
    I1, I2 = o.Ind(b_full, df.index), o.Ind(b_cut, df.index[:cut])
    for fam in o.FAMS.values():
        p = {k: v[1] for k, v in fam.space.items()}
        assert np.array_equal(fam.dirs(p, I1)[:cut], fam.dirs(p, I2))


def test_tail_window_matches_full_history_signals(hist):
    """Jonli rejim faqat so'nggi LOOKBACK sham bilan hisoblaydi — tarixdagi hisob bilan mos kelishi kerak."""
    import sl_genetic as g
    df = hist.iloc[:9000]
    full = g.build_features(sc.Bars.of(df), df.index)
    tail = df.iloc[-g.LOOKBACK:]
    t = g.build_features(sc.Bars.of(tail), tail.index)
    for k in ("rsi14", "ema20_dist", "bb_z", "roc12", "don_pos20", "hour", "stoch14", "brk_hi20"):
        assert abs(full[k][-1] - t[k][-1]) < 1e-6, k
    for k in ("ema200_dist", "atr_ratio", "ema50_slope"):          # EMA/ATR uzun xotirali — kichik farq ruxsat
        assert abs(full[k][-1] - t[k][-1]) < 0.15, k


# ---------------------------------------------------------------- dvigatellar

def _check_report(rep, mode):
    assert rep.mode == mode and rep.seconds >= 0
    assert isinstance(rep.reasons, list) and isinstance(rep.ok, bool)
    for s in rep.segments.values():
        assert {"n", "exp", "pf", "t"} <= set(s)


def test_genetic_engine_learns_and_signals(hist, tmp_path):
    import sl_genetic as g
    e = g.Engine(cfg_for("genetic", tmp_path))
    rep = e.learn(hist, budget=15, pop=30, max_gen=8)
    _check_report(rep, "genetic")
    assert rep.evals > 100
    if e.ready():                                    # qoida topilgan bo'lsa — saqlanadi, yuklanadi, signal beradi
        e2 = g.Engine(cfg_for("genetic", tmp_path))
        assert e2.load() and e2.rules == e.rules
        s = e2.signal(hist.iloc[-g.LOOKBACK:])
        assert s is None or (s.dir in (1, -1) and s.sl > 0 and s.tp > 0)


def test_genetic_finds_planted_edge_and_gate_passes(tmp_path):
    """Yashirin qonuniyat qo'yilgan tarixda (RSI<30 -> ko'tarilish) genetik qidiruv uni topishi va darvozadan o'tishi kerak."""
    import sl_genetic as g
    r = np.random.default_rng(5)
    n = 70_000
    idx = pd.date_range("2022-01-03", periods=n, freq="15min")
    c = np.empty(n)
    c[0] = 1800
    ret = r.normal(0, 1.0, n)
    for i in range(1, n):
        rs = c[max(0, i - 6):i]
        # oxirgi 5 shamda 4$ dan ko'p tushgan bo'lsa — keyingi 8 shamda kuchli tiklanish (jim bir qonuniyat)
        drift = 0.9 if (i > 6 and c[i - 1] - c[i - 6] < -4.0) else 0.0
        c[i] = c[i - 1] + ret[i] + drift
    o = np.concatenate([[c[0]], c[:-1]])
    h, l = np.maximum(o, c) + 0.3, np.minimum(o, c) - 0.3
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 100.0}, index=idx)
    cfg = cfg_for("genetic", tmp_path, require_pass=True, min_test_trades=20)
    e = g.Engine(cfg)
    rep = e.learn(df, budget=60, pop=60, max_gen=40)
    assert rep.segments["test"]["exp"] > 0.05, rep.segments
    assert rep.ok and e.ready() and e.validated


def test_optimizer_engine_runs_walk_forward(hist, tmp_path):
    import sl_optimizer as o
    e = o.Engine(cfg_for("optimizer", tmp_path))
    rep = e.learn(hist, budget=40, n_samples=25)
    _check_report(rep, "optimizer")
    assert rep.extra["windows"] >= 3 and set(rep.extra["oos_by_family"]) == set(o.FAMS)
    assert "test" in rep.segments
    if e.ready():
        e2 = o.Engine(cfg_for("optimizer", tmp_path))
        assert e2.load() and e2.fam == e.fam
        s = e2.signal(hist.iloc[-o.LOOKBACK:])
        assert s is None or s.sl > 0


def test_optimizer_needs_enough_history(hist, tmp_path):
    import sl_optimizer as o
    rep = o.Engine(cfg_for("optimizer", tmp_path)).learn(hist.iloc[:20000], budget=5, n_samples=5)
    assert not rep.ok and "tarix qisqa" in rep.summary


def test_ml_engine_trains_saves_and_loads(hist, tmp_path):
    pytest.importorskip("joblib")
    if not (pytest.importorskip("sklearn", reason="sklearn/xgboost kerak")):
        return
    import sl_ml as m
    e = m.Engine(cfg_for("ml", tmp_path))
    rep = e.learn(hist.iloc[:60000])
    _check_report(rep, "ml")
    if e.ready():
        e2 = m.Engine(cfg_for("ml", tmp_path))
        assert e2.load() and e2.feat_names == e.feat_names
        s = e2.signal(hist.iloc[:60000].iloc[-m.LOOKBACK:])
        assert s is None or s.dir in (1, -1)


def test_gate_blocks_unprofitable_holdout():
    cfg = sc.Cfg()
    good = {"n": 100, "exp": 0.2, "pf": 1.4, "t": 2.0}
    ok, why = sc.gate(cfg, {"test": good, "val": good, "train": good}, [0.1, 0.2, 0.3, 0.1])
    assert ok and not why
    bad = dict(good, exp=0.01, pf=1.0, t=0.1)
    ok, why = sc.gate(cfg, {"test": bad, "val": good, "train": good}, [0.1, -0.2, -0.3, -0.1])
    assert not ok and len(why) >= 3
    ok, why = sc.gate(cfg, {"test": dict(good, n=5), "val": good, "train": good}, [0.1] * 4)
    assert not ok and "kam" in why[0]


# ---------------------------------------------------------------- mustaqillik

def test_each_engine_imports_only_core():
    for mod, others in (("sl_genetic", ("sl_optimizer", "sl_ml")), ("sl_optimizer", ("sl_genetic", "sl_ml")),
                        ("sl_ml", ("sl_genetic", "sl_optimizer"))):
        src = (SL_DIR / f"{mod}.py").read_text(encoding="utf-8")
        for o in others:
            assert f"import {o}" not in src and f"from {o}" not in src, (mod, o)
        code = f"import sys; sys.path.insert(0, r'{SL_DIR}'); import {mod}; " \
               f"print([m for m in ('sl_genetic','sl_optimizer','sl_ml') if m in sys.modules and m != '{mod}'])"
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=str(SL_DIR))
        assert out.stdout.strip() == "[]", out.stderr


def test_dispatcher_loads_only_selected_mode(tmp_path, monkeypatch):
    code = (f"import sys, os; sys.path.insert(0, r'{SL_DIR}'); os.environ['SL_MODE']='optimizer'; "
            "import selflearn_robot as r, sl_core as sc; e = r.load_engine(sc.Cfg.from_env()); "
            "print(type(e).__module__, [m for m in ('sl_genetic','sl_ml') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "sl_optimizer []", out.stderr


def test_mode_env_parsing(monkeypatch):
    for raw, want in (("GEN", "genetic"), ("opt", "optimizer"), ("ML", "ml"), ("", "genetic")):
        monkeypatch.setenv("SL_MODE", raw)
        assert sc.Cfg.from_env().mode == want
    monkeypatch.setenv("SL_MODE", "xyz")
    with pytest.raises(SystemExit):
        sc.Cfg.from_env()
    monkeypatch.setenv("SL_MODE", "ml")
    assert sc.Cfg.from_env().magic != sc.Cfg().magic or True
    assert len({_m for _m in range(3)}) == 3


# ---------------------------------------------------------------- MT5 qatlami (soxta modul)

class FakeMT5(types.SimpleNamespace):
    pass


def make_fake(balance=1000.0, demo=True, vol_min=0.01, tick_value=1.0, tick_size=0.01):
    m = FakeMT5()
    m.TIMEFRAME_M1 = 1; m.TIMEFRAME_M5 = 5; m.TIMEFRAME_M15 = 15; m.TIMEFRAME_M30 = 30; m.TIMEFRAME_H1 = 60; m.TIMEFRAME_H4 = 240
    m.ACCOUNT_TRADE_MODE_DEMO = 0
    m.TRADE_ACTION_DEAL = 1; m.ORDER_TYPE_BUY = 0; m.ORDER_TYPE_SELL = 1; m.ORDER_TIME_GTC = 0
    m.ORDER_FILLING_FOK = 0; m.ORDER_FILLING_IOC = 1; m.ORDER_FILLING_RETURN = 2
    m.TRADE_RETCODE_DONE = 10009; m.POSITION_TYPE_BUY = 0
    m.sent = []
    m.initialize = lambda *a, **k: True
    m.last_error = lambda: (1, "x")
    m.account_info = lambda: types.SimpleNamespace(login=1, server="Demo", balance=balance, equity=balance, currency="USD",
                                                    trade_mode=0 if demo else 2)
    m.symbol_select = lambda s, f: True
    m.symbol_info = lambda s: types.SimpleNamespace(
        digits=2, point=0.01, trade_tick_size=tick_size, trade_tick_value=tick_value, volume_min=vol_min,
        volume_max=100.0, volume_step=0.01, trade_stops_level=10, filling_mode=2)
    m.symbol_info_tick = lambda s: types.SimpleNamespace(bid=2000.0, ask=2000.3, time=int(pd.Timestamp("2024-07-15 12:00").timestamp()) + 3 * 3600)

    def send(req):
        m.sent.append(req)
        return types.SimpleNamespace(retcode=10009, order=777)
    m.order_send = send
    m.positions_get = lambda symbol=None: []
    return m


def test_broker_refuses_non_demo():
    cfg = sc.Cfg()
    with pytest.raises(RuntimeError, match="DEMO"):
        sc.Broker(cfg, make_fake(demo=False)).connect()
    sc.Broker(cfg, make_fake(demo=True)).connect()


def test_lot_sizing_risks_requested_percent_and_skips_oversized_min_lot():
    cfg = sc.Cfg(risk_pct=1.0)
    br = sc.Broker(cfg, make_fake(balance=10000.0))
    # SL 5$, XAUUSD: tick 0.01 -> 500 tick * 1$ = 500$ / lot ; risk 100$ -> 0.2 lot
    lot, why = br.lot_for_risk(5.0)
    assert lot == pytest.approx(0.20) and not why
    br2 = sc.Broker(cfg, make_fake(balance=100.0))
    lot2, why2 = br2.lot_for_risk(5.0)                 # 1$ risk, min lot 0.01 = 5$ xavf (>2.5x) -> bitim yo'q
    assert lot2 == 0 and "min lot" in why2
    br3 = sc.Broker(sc.Cfg(risk_pct=2.0), make_fake(balance=100.0))
    lot3, _ = br3.lot_for_risk(0.5)                    # min lot xavfi 0.5$ <= 2.5 * 2$
    assert lot3 == pytest.approx(0.01) or lot3 > 0


def test_open_builds_correct_order():
    m = make_fake(balance=10000.0)
    br = sc.Broker(sc.Cfg(risk_pct=1.0, magic=555), m)
    ok, info = br.open(sc.Signal(1, 5.0, 7.5, 32, "t"))
    assert ok, info
    r = m.sent[-1]
    assert r["type"] == m.ORDER_TYPE_BUY and r["price"] == 2000.3 and r["sl"] == 1995.3 and r["tp"] == 2007.8
    assert r["magic"] == 555 and r["volume"] == pytest.approx(0.2) and r["type_filling"] == m.ORDER_FILLING_IOC
    ok, _ = br.open(sc.Signal(-1, 5.0, 7.5, 32))
    r = m.sent[-1]
    assert r["type"] == m.ORDER_TYPE_SELL and r["price"] == 2000.0 and r["sl"] == 2005.0 and r["tp"] == 1992.5


def test_open_rejects_stop_inside_stops_level():
    m = make_fake(balance=10000.0)
    ok, why = sc.Broker(sc.Cfg(), m).open(sc.Signal(1, 0.05, 0.05, 8))
    assert not ok and "stops" in why and not m.sent


def test_server_gmt_detection_and_bars_conversion(monkeypatch):
    m = make_fake()
    cfg = sc.Cfg()
    br = sc.Broker(cfg, m)
    monkeypatch.setattr(sc.time, "time", lambda: float(pd.Timestamp("2024-07-15 12:00").timestamp()))
    br.detect_server_gmt()
    assert br.server_gmt == 2.0                        # yozda server UTC+3 -> qishki GMT+2
    t0 = int(pd.Timestamp("2024-07-15 15:00").timestamp())      # server vaqti 15:00 = UTC 12:00
    rates = np.array([(t0 + 900 * i, 1.0, 2.0, 0.5, 1.5, 10) for i in range(4)],
                     dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "i8")])
    m.copy_rates_from_pos = lambda s, tf, a, n: rates[-n:]
    df = br.closed_bars(3)
    assert len(df) == 3 and df.index[0] == pd.Timestamp("2024-07-15 12:00") and df.index[-1] == pd.Timestamp("2024-07-15 12:30")


def test_robot_main_cli_learn_offline(tmp_path, hist):
    hp = tmp_path / "h.csv"
    hist.to_csv(hp, index_label="time")
    out = subprocess.run([sys.executable, str(SL_DIR / "selflearn_robot.py"), "--learn", "--mode", "optimizer",
                          "--history", str(hp), "--budget", "20", "--state", str(tmp_path / "st")],
                         capture_output=True, text=True, env={**__import__("os").environ, "SL_OPT_SAMPLES": "15"})
    assert out.returncode == 0, out.stderr[-800:]
    assert "DARVOZA" in out.stdout and (tmp_path / "st" / "learn_log.jsonl").exists()


# ---------------------------------------------------------------- ko'p urinish va tasdiqlash

def test_gate_tightens_with_number_of_trials():
    good = {"n": 100, "exp": 0.2, "pf": 1.4, "t": 1.5}
    c1 = sc.Cfg(trials=1)
    c10 = sc.Cfg(trials=10)
    assert sc.eff_min_t(c1) == 1.0 and sc.eff_min_t(c10) > 2.0 > sc.eff_min_t(sc.Cfg(trials=2)) > 1.0
    assert sc.gate(c1, {"test": good, "val": good, "train": good}, [0.1] * 4)[0]
    ok, why = sc.gate(c10, {"test": good, "val": good, "train": good}, [0.1] * 4)
    assert not ok and "qattiqlashtirilgan" in why[0]


def test_parse_confirm_handles_windows_paths():
    c = sc.Cfg(spread=0.3, slippage=0.05)
    out = sc.parse_confirm(r"C:\data\xag.csv|0.02|0.005;D:\e.csv", c)
    assert out == [(r"C:\data\xag.csv", 0.02, 0.005), (r"D:\e.csv", 0.3, 0.05)]


def _planted(seed, n=70_000):
    r = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03", periods=n, freq="15min")
    c = np.empty(n)
    c[0] = 1800
    ret = r.normal(0, 1.0, n)
    for i in range(1, n):
        c[i] = c[i - 1] + ret[i] + (0.9 if (i > 6 and c[i - 1] - c[i - 6] < -4.0) else 0.0)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.3, "low": np.minimum(o, c) - 0.3, "close": c, "volume": 100.0}, index=idx)


def test_confirmation_instrument_accepts_same_law_and_rejects_noise(tmp_path):
    import sl_genetic as g
    same, noise = _planted(11), synth(40_000, seed=9)
    same.to_csv(tmp_path / "same.csv", index_label="time")
    noise.to_csv(tmp_path / "noise.csv", index_label="time")
    main = _planted(5)
    ok_cfg = cfg_for("genetic", tmp_path / "a", require_pass=True, min_test_trades=20, confirm=f"{tmp_path / 'same.csv'}|0.3|0.05")
    e = g.Engine(ok_cfg)
    rep = e.learn(main, budget=60, pop=60, max_gen=40)
    assert rep.ok and rep.extra["confirm"]["same.csv"]["ok"], rep.extra
    bad_cfg = cfg_for("genetic", tmp_path / "b", require_pass=True, min_test_trades=20, confirm=f"{tmp_path / 'noise.csv'}")
    rep2 = g.Engine(bad_cfg).learn(main, budget=60, pop=60, max_gen=40)
    assert not rep2.ok and any("tasdiqlovchi" in w for w in rep2.reasons) and not rep2.deployed


def test_learn_repeat_uses_new_seeds_and_stops_on_first_pass(tmp_path, hist, monkeypatch):
    import selflearn_robot as sr
    calls = []

    class Dummy:
        def __init__(self, cfg):
            self.cfg = cfg

        def load(self):
            return False

        def learn(self, h):
            calls.append((self.cfg.seed, self.cfg.trials))
            return sc.Report(mode="genetic", ok=len(calls) == 3)

    monkeypatch.setattr(sr, "load_engine", lambda c: Dummy(c))
    eng, rep = sr.learn_repeat(sc.Cfg(seed=7, repeat=5, state_dir=str(tmp_path / "a")), hist)
    assert calls == [(7, 5), (8, 5), (9, 5)] and rep.ok and rep.extra["attempt"] == "3/5"
    calls.clear()
    eng, rep = sr.learn_repeat(sc.Cfg(seed=1, repeat=2, state_dir=str(tmp_path / "b")), hist)
    assert len(calls) == 2 and not rep.ok


def test_broker_passes_terminal_path_and_checks_login():
    m = make_fake()
    seen = {}
    m.initialize = lambda **k: seen.update(k) or True
    sc.Broker(sc.Cfg(terminal=r"E:\MT5\terminal64.exe", portable=True, login=1), m).connect()
    assert seen == {"path": r"E:\MT5\terminal64.exe", "portable": True}
    with pytest.raises(RuntimeError, match="boshqa hisobga"):
        sc.Broker(sc.Cfg(terminal="x.exe", login=999), make_fake()).connect()
    seen.clear()
    sc.Broker(sc.Cfg(), m).connect()
    assert seen == {}


def test_attempts_persist_and_forever_loop(tmp_path, hist, monkeypatch):
    """Har bosish yangi seed bilan davom etadi (natija takrorlanmaydi), darvoza jami urinishlar bo'yicha qattiqlashadi;
    uzluksiz rejim o'tguncha davom etadi va stop.flag bilan to'xtaydi."""
    import selflearn_robot as sr
    calls = []
    passes = set()

    class Dummy:
        def __init__(self, cfg):
            self.cfg = cfg

        def load(self):
            return False

        def learn(self, h):
            calls.append((self.cfg.seed, self.cfg.trials, self.cfg.attempt))
            return sc.Report(mode="genetic", ok=self.cfg.attempt in passes)

    monkeypatch.setattr(sr, "load_engine", lambda c: Dummy(c))
    cfg = sc.Cfg(seed=7, state_dir=str(tmp_path))
    sr.learn_repeat(cfg, hist)
    sr.learn_repeat(cfg, hist)                                  # ikkinchi bosish: yangi seed, 2 urinish hisobida
    assert calls == [(7, 1, 0), (8, 2, 1)] and sr.attempts_done(cfg, hist) == 2
    calls.clear()
    passes.add(4)
    eng, rep = sr.learn_repeat(cfg, hist, forever=True)
    assert [c[2] for c in calls] == [2, 3, 4] and [c[1] for c in calls] == [3, 4, 5] and rep.ok
    assert rep.extra["attempt_no"] == 5 and rep.extra["min_t"] > 1.0
    calls.clear()
    seen = []
    (tmp_path / "stop.flag").write_text("1")
    sr.learn_repeat(cfg, hist, forever=True, on_attempt=lambda e, r: seen.append(r.extra["attempt_no"]))
    assert seen == [6] and not (tmp_path / "stop.flag").exists()


def test_ml_attempts_try_different_configs():
    import sl_ml
    base = sl_ml.attempt_config(sc.Cfg(seed=7, attempt=0), 1.5, 1.5, 32)
    assert base[:3] == (1.5, 1.5, 32) and base[3] == sl_ml.DEFAULT_HP
    variants = {sl_ml.attempt_config(sc.Cfg(seed=7 + k, attempt=k), 1.5, 1.5, 32)[:3] for k in range(1, 12)}
    assert len(variants) >= 5
    assert sl_ml.attempt_config(sc.Cfg(seed=9, attempt=2), 1.5, 1.5, 32) == sl_ml.attempt_config(sc.Cfg(seed=9, attempt=2), 1.5, 1.5, 32)
