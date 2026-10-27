import numpy as np
import pandas as pd
import pytest

from conftest import synth
from mor import features as F
from mor import importers
from mor.agent import Agent, Replay
from mor.env import BUY, CLOSE, HOLD, SELL, Env, EnvCfg, make_series, make_obs, OBS_DIM
from mor.lessons import Guard, MineCfg, mine
from mor.trainer import TrainCfg, Trainer, trade_stats


# ------------------------------------------------------------ baza
def test_db_bars_roundtrip_and_datasets(db, df):
    assert db.put_bars("XAUUSD", "M15", df) == len(df)
    out = db.get_bars("XAUUSD", "M15")
    assert len(out) == len(df) and np.allclose(out["close"], df["close"]) and out.index[0] == df.index[0]
    assert db.datasets()[0]["bars"] == len(df)
    assert len(db.get_bars("XAUUSD", "M15", start=int(df.index[100].timestamp()), end=int(df.index[199].timestamp()))) == 100
    db.put_bars("XAUUSD", "M15", df.iloc[:10])                      # qayta yozish ko'paytirmaydi
    assert db.datasets()[0]["bars"] == len(df)


def test_db_experiences_lessons_policies(db):
    rows = [{"symbol": "X", "tf": "M15", "ts_open": 1, "ts_close": 2, "side": 1, "r": 0.5, "state": np.ones(F.N_FEATURES)},
            {"symbol": "X", "tf": "M15", "ts_open": 3, "ts_close": 4, "side": -1, "r": -1.0, "state": np.zeros(F.N_FEATURES)}]
    assert db.add_experiences(1, "train", rows) == 2
    assert db.experience_stats()["n"] == 2
    arr = db.experience_arrays("train")
    assert arr["X"].shape == (2, F.N_FEATURES) and list(arr["side"]) == [1, -1]
    assert [e["r"] for e in db.experiences(outcome="loss")] == [-1.0]
    db.replace_lessons(1, [{"kind": "avoid", "text": "t", "rule": {"side": 0, "clauses": []}, "n": 5, "exp": -0.1, "t": -3,
                            "status": "verified"}])
    assert db.lessons("verified")[0]["rule"]["side"] == 0
    db.add_policy(1, 1, "p.npz", {"a": 1}, True)
    assert db.latest_policy(True)["version"] == 1


def test_calendar_events(db):
    ev = pd.DataFrame({"time": ["2024-01-05 13:30", "2024-01-05 15:00"], "currency": ["usd", "eur"], "impact": [3, 2],
                       "title": ["NFP", "x"]})
    assert db.put_events(ev) == 2
    assert len(db.get_events(["USD"], min_impact=3)) == 1


# ------------------------------------------------------------ importerlar
def test_import_mt5_style_csv_and_resample(tmp_path, db):
    p = tmp_path / "XAUUSD_M1.csv"
    idx = pd.date_range("2024-01-01", periods=60, freq="1min")
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for i, t in enumerate(idx):
        lines.append("%s\t%s\t%.2f\t%.2f\t%.2f\t%.2f\t10\t0\t30" % (t.strftime("%Y.%m.%d"), t.strftime("%H:%M:%S"),
                                                                    2000 + i, 2001 + i, 1999 + i, 2000.5 + i))
    p.write_text("\n".join(lines), encoding="utf-8")
    r = importers.import_csv(db, str(p), target_tf="M15")
    assert r["symbol"] == "XAUUSD" and r["tf"] == "M15" and r["bars"] == 4
    b = db.get_bars("XAUUSD", "M15")
    assert b["open"].iloc[0] == 2000 and b["high"].iloc[0] == 2015 and b["close"].iloc[0] == 2014.5
    assert abs(b["spread"].iloc[0] - 0.30) < 1e-9                    # 30 punkt * 0.01


def test_import_simple_csv_with_default_spread(tmp_path, db, df):
    p = tmp_path / "EURUSD_M15.csv"
    d2 = df.copy()
    d2.index.name = "time"
    d2.drop(columns=["spread"]).to_csv(p)
    importers.import_csv(db, str(p))
    assert db.instrument("EURUSD")["default_spread"] > 0
    assert db.get_bars("EURUSD", "M15")["spread"].iloc[0] == db.instrument("EURUSD")["default_spread"]


# ------------------------------------------------------------ belgilar
def test_features_have_no_lookahead(df):
    X1, _ = F.build_features(df)
    d2 = df.copy()
    d2.iloc[3000:, d2.columns.get_loc("close")] += 50.0              # kelajakni buzamiz
    d2.iloc[3000:, d2.columns.get_loc("high")] += 50.0
    X2, _ = F.build_features(d2)
    assert np.allclose(X1[:3000], X2[:3000], atol=1e-6)
    assert X1.shape == (len(df), F.N_FEATURES) and np.isfinite(X1).all()


def test_news_features_distance():
    ts = np.array([0, 600, 3600], dtype=np.int64)
    nxt, prv = F.news_features(ts, np.array([1800], dtype=np.int64))
    assert nxt[0] < nxt[2] or prv[2] > prv[1]
    assert nxt[1] < 1.0 and prv[0] == 1.0


# ------------------------------------------------------------ muhit
def _flat_series(n=300, price=100.0, spread=0.2):
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    d = pd.DataFrame({"open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1.0,
                      "spread": spread}, index=idx)
    return make_series("T", "M15", d)


def test_env_stop_loss_costs_exactly_one_r_plus_costs():
    s = _flat_series()
    j = 200
    s.l[j + 1] = s.c[j] - 100.0                                      # keyingi shamda SL uriladi
    e = Env(EnvCfg(sl_atr=1.5, slippage_atr=0.0))
    e.reset(s, j, 280)
    _, r, d, info = e.step(BUY)
    assert e.side == 0 and info is not None and info["reason"] == "stop"
    assert abs(info["r"] + 1.0) < 1e-9                                # SL aynan -1R (spred kirish narxida hisobda)
    e2 = Env(EnvCfg(sl_atr=1.5, slippage_atr=0.05))                   # sirpanish bo'lsa -1R dan yomonroq
    e2.reset(s, j, 280)
    assert e2.step(BUY)[3]["r"] < -1.0
    assert abs(r - info["r"]) < 1e-9                                 # mukofot yig'indisi = bitim natijasi


def test_env_reward_sums_to_trade_r_and_close_action():
    s = _flat_series()
    s.c[201:] += np.linspace(0, 2, len(s.c) - 201)
    s.o[201:] = s.c[201:]
    s.h[201:] = s.c[201:] + 0.3
    s.l[201:] = s.c[201:] - 0.3
    e = Env(EnvCfg(slippage_atr=0.01))
    e.reset(s, 200, 290)
    rew = 0.0
    _, r, _, info = e.step(BUY)
    rew += r
    for _ in range(5):
        _, r, _, info = e.step(HOLD)
        rew += r
    _, r, _, info = e.step(CLOSE)
    rew += r
    assert info is not None and info["reason"] == "agent" and info["bars_held"] >= 5
    assert abs(rew - info["r"]) < 1e-9


def test_env_short_pays_spread_and_time_exit():
    s = _flat_series()
    e = Env(EnvCfg(max_hold=10, slippage_atr=0.0))
    e.reset(s, 100, 290)
    e.step(SELL)
    info = None
    for _ in range(15):
        _, _, _, info = e.step(HOLD)
        if info:
            break
    assert info is not None and info["reason"] == "vaqt" and info["side"] == -1
    assert info["r"] < 0                                              # tekis bozor: faqat xarajat


def test_env_obs_matches_make_obs():
    s = _flat_series()
    e = Env()
    e.reset(s, 150, 280)
    assert np.allclose(e.obs(), make_obs(s.X[150]))
    e.step(BUY)
    ob = e.obs()
    assert ob[F.N_FEATURES] == 1 and ob.shape == (OBS_DIM,)


# ------------------------------------------------------------ agent
def test_agent_learns_simple_reward_and_roundtrips(tmp_path):
    ag = Agent(hidden=(32,), lr=1e-2, gamma=0.0, seed=0)
    rb = Replay(5000)
    rng = np.random.default_rng(0)
    for _ in range(3000):
        o = np.zeros(OBS_DIM, np.float32)
        o[0] = rng.choice([-1.0, 1.0])
        a = int(rng.integers(0, 3))
        r = 1.0 if (a == 1 and o[0] > 0) or (a == 2 and o[0] < 0) else (0.0 if a == 0 else -1.0)
        rb.add(o, a, r, o, 1.0)
    for _ in range(600):
        ag.learn(rb, 64, F.N_FEATURES)
    o = np.zeros((2, OBS_DIM), np.float32)
    o[0, 0], o[1, 0] = 1.0, -1.0
    m = Agent.mask_from_obs(o, F.N_FEATURES)
    assert list(ag.act(o, m, 0.0)) == [1, 2]
    p = tmp_path / "a.npz"
    ag.save(str(p), {"x": 1})
    ag2 = Agent.load(str(p))
    assert np.allclose(ag.q_values(o), ag2.q_values(o)) and Agent.load_meta(str(p)) == {"x": 1}


def test_replay_tags_and_mixed_sampling():
    rb = Replay(200)
    o = np.zeros(OBS_DIM, np.float32)
    ids = [rb.add(o, 0, float(i), o, 0.0) for i in range(100)]
    rb.mark(ids[:10], 1)
    rb.mark(ids[10:20], 2)
    idx, w = rb.sample(50, np.random.default_rng(0), 0.2, 0.2)
    tags = rb.tag[idx]
    assert (tags == 1).sum() >= 8 and (tags == 2).sum() >= 8 and len(idx) == 50 and w.max() <= 1.0 + 1e-6


# ------------------------------------------------------------ qonuniyat qidirish
def _fake_exp(n, seed, planted):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, F.N_FEATURES)).astype(np.float32)
    side = rng.choice([1, -1], n)
    r = rng.standard_normal(n) * 1.0 - 0.05
    if planted:
        j = F.NAMES.index("spread")
        r = np.where(X[:, j] > 0.5, r - 0.8, r)
    return {"X": X, "side": side, "r": r, "ts": np.arange(n), "symbol": np.array(["X"] * n, dtype=object)}


def test_lessons_find_planted_rule_and_verify_out_of_sample():
    ls = mine(_fake_exp(6000, 1, True), _fake_exp(3000, 2, True))
    ver = [x for x in ls if x["status"] == "verified" and x["kind"] == "avoid"]
    assert ver and any("spred" in x["text"] for x in ver)
    g = Guard(ls)
    row = np.zeros(F.N_FEATURES, np.float32)
    row[F.NAMES.index("spread")] = 2.0
    assert g.veto(row, 1) and not g.veto(np.zeros(F.N_FEATURES, np.float32), 1)


def test_lessons_reject_noise_oos():
    ls = mine(_fake_exp(6000, 3, False), _fake_exp(3000, 4, False))
    assert sum(1 for x in ls if x["status"] == "verified") <= 1


# ------------------------------------------------------------ o'qitish (kichik)
def test_trainer_runs_end_to_end_and_stores_memory(db, df, tmp_path, monkeypatch):
    monkeypatch.setenv("MYOWNROBOT_HOME", str(tmp_path))
    db.put_bars("XAUUSD", "M15", df)
    db.put_bars("EURUSD", "M15", synth(5000, seed=5, base=1.1, vol=0.001, spread=0.00012))
    events = []
    cfg = TrainCfg(epochs=4, envs=4, episode_len=400, eval_every=2, warmup=300, min_trades=10, batch=32)
    m = Trainer(db, cfg, events.append).run()
    assert db.experience_stats()["n"] > 0 and db.count("policies") == 1
    assert {"val", "test", "gate_ok", "per_symbol_test"} <= set(m)
    assert any(e["type"] == "epoch" and "val" in e for e in events) and events[-1]["type"] == "done"
    assert set(m["symbols"]) == {"XAUUSD", "EURUSD"}
    # davom ettirish: oldingi siyosat yuklanadi
    ev2 = []
    Trainer(db, TrainCfg(epochs=1, envs=4, episode_len=400, eval_every=1, warmup=300, min_trades=10), ev2.append).run()
    assert any("davom" in e.get("msg", "") for e in ev2)


def test_trainer_can_be_stopped(db, df, tmp_path, monkeypatch):
    monkeypatch.setenv("MYOWNROBOT_HOME", str(tmp_path))
    db.put_bars("XAUUSD", "M15", df)
    n = {"c": 0}

    def stop():
        n["c"] += 1
        return n["c"] > 2
    m = Trainer(db, TrainCfg(epochs=50, envs=4, episode_len=300, eval_every=1, warmup=100, min_trades=5), None, stop).run()
    assert len(m["history"]) == 2


def test_trade_stats_math():
    s = trade_stats(np.array([1.0, -1.0, 2.0, -0.5]))
    assert s["n"] == 4 and abs(s["exp"] - 0.375) < 1e-9 and abs(s["pf"] - 3.0 / 1.5) < 1e-9 and s["dd"] == 1.0


# ------------------------------------------------------------ jonli sikl
class FakeBroker:
    def __init__(self, df, demo=True):
        self.df, self.pos, self.opened, self.closed = df, None, [], []
        self.eq = 10000.0

    def bars(self, n):
        return self.df.iloc[-n:]

    def account(self):
        return {"balance": self.eq, "equity": self.eq}

    def position(self):
        return self.pos

    def tick(self):
        c = float(self.df["close"].iloc[-1])
        return {"bid": c, "ask": c + 0.3}

    def lots_for(self, risk_money, sl_dist):
        return round(risk_money / sl_dist / 100, 2)

    def open(self, side, lots, sl):
        t = self.tick()
        self.pos = {"ticket": 7, "side": side, "entry": t["ask"] if side > 0 else t["bid"], "sl": sl, "volume": lots,
                    "time": int(self.df.index[-1].timestamp()), "profit": 0.0}
        self.opened.append((side, lots, sl))
        return {"ticket": 7, "price": self.pos["entry"]}

    def close(self, pos):
        self.pos = None
        self.closed.append(pos["ticket"])
        return {"price": 1.0}

    def deal_profit(self, ticket):
        return -25.0


def test_live_runner_opens_closes_and_tracks_r(df, tmp_path):
    from mor.live import LiveCfg, LiveRunner
    ag = Agent(hidden=(16,), seed=0)
    ag.q.b[-1][:] = [0.0, 1.0, 0.0, 0.0]                              # har doim BUY ni afzal ko'radi
    ag.save(str(tmp_path / "p.npz"), {"env": {"sl_atr": 1.5, "max_hold": 96}, "guard": []})
    br = FakeBroker(df.iloc[:2000].copy())
    cfg = LiveCfg(risk_pct=0.5, tf="M15")
    ev = []
    lr = LiveRunner(cfg, str(tmp_path / "p.npz"), br, on_event=ev.append)
    e1 = lr.step_once()
    assert e1["action"] == "BUY" and br.opened and br.opened[0][1] > 0 and br.opened[0][2] < br.pos["entry"]
    assert lr.step_once() is None                                    # o'sha sham — qaror yo'q
    br.df = df.iloc[:2001].copy()
    br.pos = None                                                    # SL urildi
    lr.step_once()
    assert any(x["type"] == "trade_closed" and abs(x["r"] + 25.0 / (10000 * 0.005)) < 1e-6 for x in ev)


def test_live_kill_switch_and_daily_limit(df, tmp_path):
    from mor.live import LiveCfg, LiveRunner
    Agent(hidden=(16,), seed=0).save(str(tmp_path / "p.npz"), {})
    br = FakeBroker(df.iloc[:2000].copy())
    lr = LiveRunner(LiveCfg(), str(tmp_path / "p.npz"), br)
    assert lr.risk_blocked() == ""
    lr.recent_r = [-0.5] * 20
    assert "to'xtatish" in lr.risk_blocked()
    lr.recent_r = []
    br.eq = 10000 * 0.97
    assert "kunlik" in lr.risk_blocked()


def test_live_guard_vetoes_entry(df, tmp_path):
    from mor.live import LiveCfg, LiveRunner
    ag = Agent(hidden=(16,), seed=0)
    ag.q.b[-1][:] = [0.0, 1.0, 0.0, 0.0]
    rule = {"side": 0, "clauses": [{"f": 0, "op": "<=", "v": 1e9}]}                     # hamma holatga mos
    ag.save(str(tmp_path / "p.npz"), {"guard": [{"status": "verified", "kind": "avoid", "rule": rule}]})
    br = FakeBroker(df.iloc[:2000].copy())
    lr = LiveRunner(LiveCfg(), str(tmp_path / "p.npz"), br)
    assert lr.step_once()["action"] == "KUTISH" and not br.opened


def test_calendar_import_mql_format(tmp_path):
    from mor.db import Database
    from mor.importers import import_calendar_csv
    p = tmp_path / "calendar.csv"
    p.write_text("time,currency,impact,title,actual,forecast,previous\n"
                 "2022.01.07 15:30,USD,3,Nonfarm Payrolls,199.0,422.0,249.0\n"
                 "2022.01.07 10:00,EUR,2,Some data,,,\n"
                 "2022.01.08 10:00,EUR,0,Holiday,,,\n", encoding="utf-8")
    db = Database(tmp_path / "c.db")
    assert import_calendar_csv(db, str(p), tz_offset_hours=2) == 2           # ta'siri 0 bo'lgani tashlanadi
    e = db.get_events(min_impact=3)
    assert len(e) == 1 and e["currency"][0] == "USD"
    import pandas as pd
    assert pd.Timestamp(int(e["ts"][0]), unit="s", tz="UTC").strftime("%Y-%m-%d %H:%M") == "2022-01-07 13:30"   # 15:30 − 2 soat
    p2 = tmp_path / "bad.csv"
    p2.write_text("a,b\n1,2\n")
    import pytest
    with pytest.raises(ValueError):
        import_calendar_csv(db, str(p2))
