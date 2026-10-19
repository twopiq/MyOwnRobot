"""Rejim 2 · OPTIMIZER — tayyor strategiya oilalarining parametrlarini walk-forward usulida qayta optimallashtiradi.

Uch oila: trend_pullback (trend ichida orqaga qaytish), donchian (kanal yorilishi yoki uning teskarisi),
bb_revert (Bollinger z-score: qaytish yoki davom). Har oila uchun:
  1. Rolling oynalar: 18 oy train -> keyingi 3 oy "ko'r" test (oyna 3 oyga suriladi).
  2. Train'da tasodifiy qidiruv + qo'shni parametrlar bilan silliqlash (o'tkir cho'qqini emas, barqaror hududni tanlaydi).
  3. Barcha test oynalari ulanib bitta "haqiqiy" OOS natija beradi — qabul darvozasi shu natijaga qo'llanadi.
Eng yaxshi oila oxirgi 18 oyda qayta optimallanib jonli savdoga beriladi; har relearn siklida jarayon takrorlanadi.

Bu fayl faqat sl_core dan foydalanadi (boshqa dvigatellarni import qilmaydi).
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sl_core as sc

NAME = "optimizer"
LOOKBACK = 700
TRAIN_MONTHS = 18
TEST_MONTHS = 3
SESS = [(0, 24), (7, 17), (7, 12), (12, 17), (13, 20), (0, 8), (20, 24)]

COMMON = {"sl": [1.0, 1.5, 2.0, 2.5, 3.0], "rr": [1.0, 1.5, 2.0, 3.0], "hold": [16, 32, 48, 96], "sess": list(range(len(SESS)))}


class Ind:
    """Indikator keshi (bir tarix uchun)."""

    def __init__(self, b: sc.Bars, idx: pd.DatetimeIndex):
        self.b, self.n = b, len(b)
        self.hour = sc.hour_utc(idx)
        self.atr = sc.atr(b.h, b.l, b.c, 14)
        a100 = sc.atr(b.h, b.l, b.c, 100)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.atr_ratio = np.nan_to_num(self.atr / a100, nan=1.0)
        self._c: Dict[Tuple[str, int], np.ndarray] = {}

    def get(self, kind: str, n: int) -> np.ndarray:
        k = (kind, n)
        if k not in self._c:
            b = self.b
            if kind == "ema":
                x = sc.ema(b.c, n)
            elif kind == "rsi":
                x = sc.rsi(b.c, n)
            elif kind == "hh":
                x = sc.shift(sc.rmax(b.h, n), 1)
            elif kind == "ll":
                x = sc.shift(sc.rmin(b.l, n), 1)
            elif kind == "z":
                with np.errstate(divide="ignore", invalid="ignore"):
                    x = (b.c - sc.sma(b.c, n)) / sc.rstd(b.c, n)
            else:
                raise KeyError(kind)
            self._c[k] = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        return self._c[k]


class Fam:
    name = ""
    space: Dict[str, list] = {}

    def dirs(self, p: Dict[str, Any], I: Ind) -> np.ndarray:  # +1 / -1 / 0 har sham uchun
        raise NotImplementedError


class TrendPullback(Fam):
    name = "trend_pullback"
    space = {"ef": [8, 13, 21, 34], "es": [50, 89, 144, 200], "rsi_n": [5, 7, 14], "rsi_th": [25, 30, 35, 40, 45, 50], **COMMON}

    def dirs(self, p, I):
        ef, es, r = I.get("ema", p["ef"]), I.get("ema", p["es"]), I.get("rsi", p["rsi_n"])
        c = I.b.c
        d = np.zeros(I.n, dtype=np.int8)
        d[(ef > es) & (c > es) & (r < p["rsi_th"])] = 1
        d[(ef < es) & (c < es) & (r > 100 - p["rsi_th"])] = -1
        return d


class Donchian(Fam):
    name = "donchian"
    space = {"n": [12, 20, 30, 48, 96], "atr_min": [0.0, 0.8, 1.0, 1.2], "trend": [0, 100, 200], "fade": [0, 1], **COMMON}

    def dirs(self, p, I):
        c = I.b.c
        hh, ll = I.get("hh", p["n"]), I.get("ll", p["n"])
        up, dn = (c > hh) & (hh > 0), (c < ll) & (ll > 0)
        if p["fade"]:
            up, dn = dn, up       # kanal chegarasidan teskari (qaytish) — long pastki chegarada
            d = np.zeros(I.n, dtype=np.int8)
            d[up] = 1
            d[dn] = -1
        else:
            d = np.zeros(I.n, dtype=np.int8)
            if p["trend"]:
                e = I.get("ema", p["trend"])
                up, dn = up & (c > e), dn & (c < e)
            d[up] = 1
            d[dn] = -1
        d[I.atr_ratio < p["atr_min"]] = 0
        return d


class BBRevert(Fam):
    name = "bb_revert"
    space = {"n": [14, 20, 30, 50], "z": [1.5, 2.0, 2.5, 3.0], "atr_max": [1.0, 1.3, 1.7, 9.0], "mom": [0, 1], **COMMON}

    def dirs(self, p, I):
        z = I.get("z", p["n"])
        d = np.zeros(I.n, dtype=np.int8)
        lo, hi = z < -p["z"], z > p["z"]
        if p["mom"]:
            lo, hi = hi, lo
        d[lo] = 1
        d[hi] = -1
        d[I.atr_ratio > p["atr_max"]] = 0
        return d


FAMS: Dict[str, Fam] = {f.name: f for f in (TrendPullback(), Donchian(), BBRevert())}


def _idx_params(fam: Fam, vec: Tuple[int, ...]) -> Dict[str, Any]:
    return {k: fam.space[k][i] for k, i in zip(fam.space, vec)}


def _sess_mask(I: Ind, s: int) -> np.ndarray:
    a, b = SESS[s]
    return (I.hour >= a) & (I.hour < b)


def trades_for(fam: Fam, p: Dict[str, Any], I: Ind, cfg: sc.Cfg, lo: int, hi: int) -> sc.Trades:
    d = fam.dirs(p, I)
    d = np.where(_sess_mask(I, p["sess"]), d, 0)
    idx = np.nonzero(d)[0]
    idx = idx[(idx >= lo) & (idx < hi)]
    if len(idx) == 0 or len(idx) > 30000:
        return sc.Trades.empty()
    a = I.atr[idx]
    return sc.simulate(I.b, idx, d[idx], p["sl"] * a, p["sl"] * p["rr"] * a, p["hold"], cfg.spread, cfg.slippage, lo=lo, hi=hi)


def optimize(fam: Fam, I: Ind, cfg: sc.Cfg, lo: int, hi: int, n_samples: int, rng: np.random.Generator,
             min_n: int) -> Tuple[Optional[Tuple[int, ...]], float, float, int]:
    """Tasodifiy qidiruv + qo'shni parametrlar bilan silliqlash. Qaytaradi: (vektor, o'z balli, silliqlangan ball, baholar soni)."""
    keys = list(fam.space)
    sizes = [len(fam.space[k]) for k in keys]
    seen: Dict[Tuple[int, ...], float] = {}

    def score(vec: Tuple[int, ...]) -> float:
        if vec not in seen:
            t = trades_for(fam, _idx_params(fam, vec), I, cfg, lo, hi)
            seen[vec] = sc.consistent_score(t, lo, hi, min_n)
        return seen[vec]

    for _ in range(n_samples):
        score(tuple(int(rng.integers(s)) for s in sizes))
    top = sorted(seen, key=lambda v: -seen[v])[:12]
    best, best_sm = None, -99.0
    for v in top:
        vals = [seen[v]]
        for _ in range(6):
            j = int(rng.integers(len(keys)))
            w = list(v)
            w[j] = int(np.clip(w[j] + rng.choice([-1, 1]), 0, sizes[j] - 1))
            vals.append(score(tuple(w)))
        sm = float(np.mean(vals))
        if sm > best_sm:
            best, best_sm = v, sm
    return best, (seen[best] if best else -9.0), best_sm, len(seen)


class Engine:
    name = NAME
    lookback = LOOKBACK

    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.fam: str = ""
        self.params: Dict[str, Any] = {}
        self.validated = False

    def ready(self) -> bool:
        return bool(self.fam and self.params)

    def describe(self) -> str:
        if not self.ready():
            return "(strategiya yo'q)"
        return "%s %s" % (self.fam, json.dumps(self.params, ensure_ascii=False))

    def save(self) -> None:
        sc.state_path(self.cfg, "optimizer_strategy.json").write_text(
            json.dumps({"fam": self.fam, "params": self.params, "validated": self.validated}, indent=1), encoding="utf-8")

    def load(self) -> bool:
        p = sc.state_path(self.cfg, "optimizer_strategy.json")
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("fam") in FAMS:
                    self.fam, self.params, self.validated = d["fam"], d["params"], bool(d.get("validated"))
            except Exception:  # noqa: BLE001
                return False
        return self.ready()

    def signal(self, df: pd.DataFrame) -> Optional[sc.Signal]:
        if not self.ready() or len(df) < sc.WARMUP:
            return None
        b = sc.Bars.of(df)
        I = Ind(b, df.index)
        p = self.params
        d = int(FAMS[self.fam].dirs(p, I)[-1])
        a, s = SESS[p["sess"]]
        if d == 0 or not (a <= I.hour[-1] < s):
            return None
        return sc.Signal(d, p["sl"] * I.atr[-1], p["sl"] * p["rr"] * I.atr[-1], int(p["hold"]), self.fam[:8])

    # ------------------------------------------------------------ o'rganish
    def learn(self, hist: pd.DataFrame, budget: Optional[float] = None, n_samples: Optional[int] = None,
              progress: Optional[Callable[..., None]] = None) -> sc.Report:
        t0 = time.time()
        cfg = self.cfg
        budget = cfg.budget_sec if budget is None else budget
        n_samples = n_samples or sc.env_i("SL_OPT_SAMPLES", 200)
        b = sc.Bars.of(hist)
        I = Ind(b, hist.index)
        n = len(b)
        ts = hist.index
        t_first = ts[0] + pd.DateOffset(months=TRAIN_MONTHS)
        starts: List[pd.Timestamp] = []
        t = t_first
        while t + pd.DateOffset(months=TEST_MONTHS) <= ts[-1] + pd.Timedelta(days=3):
            starts.append(t)
            t += pd.DateOffset(months=TEST_MONTHS)
        rep = sc.Report(mode=NAME)
        if len(starts) < 3:
            rep.summary = "tarix qisqa: kamida %d oy kerak" % (TRAIN_MONTHS + 3 * TEST_MONTHS)
            rep.reasons = [rep.summary]
            return rep
        pos = lambda x: int(ts.searchsorted(x))                      # noqa: E731
        evals = 0
        oos: Dict[str, List[sc.Trades]] = {k: [] for k in FAMS}
        win_means: Dict[str, List[float]] = {k: [] for k in FAMS}
        per_budget = budget * 0.85 / max(1, len(FAMS))
        for fi, (fn, fam) in enumerate(FAMS.items()):
            f0 = time.time()
            for wi, st in enumerate(starts):
                lo, mid = pos(st - pd.DateOffset(months=TRAIN_MONTHS)), pos(st)
                hi = min(n, pos(st + pd.DateOffset(months=TEST_MONTHS)))
                spent = time.time() - f0
                left = len(starts) - wi
                ns = n_samples
                if wi > 0 and spent / wi * left > per_budget - spent:        # vaqtga sig'dirish uchun tanlamani kamaytiramiz
                    ns = max(40, int(n_samples * max(0.2, (per_budget - spent) / max(1e-6, spent / wi * left))))
                v, s_tr, s_sm, ne = optimize(fam, I, cfg, lo, mid, ns, self.rng, min_n=40)
                evals += ne
                if v is None:
                    continue
                tt = trades_for(fam, _idx_params(fam, v), I, cfg, mid, hi)
                oos[fn].append(tt)
                win_means[fn].append(float(tt.R.mean()) if len(tt) else 0.0)
                if progress:
                    progress(fn, wi, len(starts), s_tr)
        # --- har oila uchun ulangan OOS natija
        stitched: Dict[str, Tuple[sc.Trades, Dict[str, float]]] = {}
        for fn in FAMS:
            ts_ = [x for x in oos[fn] if len(x)]
            if ts_:
                tr = sc.Trades(*[np.concatenate([getattr(x, f) for x in ts_]) for f in ("entry_i", "exit_i", "dirs", "R", "pnl")])
            else:
                tr = sc.Trades.empty()
            stitched[fn] = (tr, sc.stats(tr))
        order = sorted(FAMS, key=lambda k: -stitched[k][1]["t"])
        best = order[0]
        rep.extra = {"oos_by_family": {k: {"n": stitched[k][1]["n"], "exp": round(stitched[k][1]["exp"], 3),
                                          "t": round(stitched[k][1]["t"], 2), "pos_windows": round(
                                              float(np.mean([x > 0 for x in win_means[k]])) if win_means[k] else 0, 2)}
                                    for k in FAMS},
                     "windows": len(starts), "best_family": best}
        # --- yakuniy parametrlar: eng yaxshi oila oxirgi 18 oyda qayta optimallanadi
        fam = FAMS[best]
        lo, hi = pos(ts[-1] - pd.DateOffset(months=TRAIN_MONTHS)), n
        v, s_tr, s_sm, ne = optimize(fam, I, cfg, lo, hi, n_samples * 2, self.rng, min_n=40)
        evals += ne
        rep.evals = evals
        if v is None:
            rep.summary = "oxirgi oynada parametr topilmadi"
            rep.reasons = [rep.summary]
            return rep
        params = _idx_params(fam, v)
        last = trades_for(fam, params, I, cfg, lo, hi)
        rep.segments = {"test": stitched[best][1], "train": sc.stats(last)}
        ok, why = sc.gate(cfg, {"test": rep.segments["test"]}, win_means[best])
        conf = sc.make_confirm(cfg)
        if ok and conf:
            def _ev(d, sp_, sj_):
                c2 = sc.Cfg(spread=sp_, slippage=sj_)
                I2 = Ind(sc.Bars.of(d), d.index)
                return trades_for(fam, params, I2, c2, 0, len(d))
            ok2, why2, info = conf(_ev)
            ok, why = ok and ok2, why + why2
            rep.extra["confirm"] = info
        rep.ok, rep.reasons = ok, why
        rep.strategy = "%s %s" % (best, json.dumps(params, ensure_ascii=False))
        if ok or (not cfg.require_pass and not self.ready()):
            self.fam, self.params, self.validated = best, params, ok
            self.save()
            rep.deployed = True
        rep.seconds = time.time() - t0
        rep.summary = "%d oyna x %d oila, %d baho; eng yaxshi oila: %s" % (len(starts), len(FAMS), evals, best)
        return rep
