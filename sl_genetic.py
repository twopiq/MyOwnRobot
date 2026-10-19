"""Rejim 1 · GENETIC — kirish qoidalarini evolyutsiya (genetik qidiruv) bilan o'zi yaratadi.

Genom = 1-3 ta shart ("indikator  >/<  chegara") + yo'nalish + SL(ATR ko'paytmasi) + RR + ushlab turish muddati.
Chegaralar train davridagi kvantillardan olinadi. Populyatsiya: tanlov (turnir), chatishtirish, mutatsiya, elita,
tasodifiy "immigrantlar". Maqsad: xarajatlardan keyingi t-statistika (bitimlar soni va davrlar bo'yicha barqarorlik
hisobga olinadi). Eng yaxshi qoidalar validatsiyada saralanadi, oxirgi tegilmagan holdout'da tekshiriladi.

Bu fayl faqat sl_core dan foydalanadi (boshqa dvigatellarni import qilmaydi).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sl_core as sc

NAME = "genetic"
LOOKBACK = 700                      # jonli signal uchun kerak bo'lgan shamlar soni
QGRID = np.linspace(0.05, 0.95, 19)
SL_GRID = [0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
RR_GRID = [0.8, 1.0, 1.5, 2.0, 3.0]
HOLD_GRID = [16, 32, 48, 96]
MAX_CONDS = 3


def build_features(b: sc.Bars, idx: pd.DatetimeIndex) -> Dict[str, np.ndarray]:
    """Genetik qidiruv ishlatadigan xususiyatlar kutubxonasi (hammasi ATR ga nisbatan — narx darajasidan mustaqil)."""
    o, h, l, c, v = b.o, b.h, b.l, b.c, b.v
    a14 = sc.atr(h, l, c, 14)
    a100 = sc.atr(h, l, c, 100)
    with np.errstate(divide="ignore", invalid="ignore"):
        f: Dict[str, np.ndarray] = {}
        f["rsi14"] = sc.rsi(c, 14)
        f["rsi5"] = sc.rsi(c, 5)
        for n in (20, 50, 200):
            f[f"ema{n}_dist"] = (c - sc.ema(c, n)) / a14
        e20 = sc.ema(c, 20)
        f["ema20_slope"] = (e20 - sc.shift(e20, 5)) / a14
        e50 = sc.ema(c, 50)
        f["ema50_slope"] = (e50 - sc.shift(e50, 10)) / a14
        s20, sd20 = sc.sma(c, 20), sc.rstd(c, 20)
        f["bb_z"] = (c - s20) / sd20
        f["atr_ratio"] = a14 / a100
        for k in (3, 12, 48):
            f[f"roc{k}"] = (c - sc.shift(c, k)) / a14
        f["body"] = (c - o) / a14
        f["range"] = (h - l) / a14
        f["upper_wick"] = (h - np.maximum(o, c)) / a14
        f["lower_wick"] = (np.minimum(o, c) - l) / a14
        hh20, ll20 = sc.rmax(h, 20), sc.rmin(l, 20)
        f["don_pos20"] = (c - ll20) / (hh20 - ll20)
        f["brk_hi20"] = (c - sc.shift(hh20, 1)) / a14
        f["brk_lo20"] = (sc.shift(ll20, 1) - c) / a14
        hh, ll = sc.rmax(h, 14), sc.rmin(l, 14)
        f["stoch14"] = 100.0 * (c - ll) / (hh - ll)
        f["vol_ratio"] = v / sc.sma(v, 50)
        f["hour"] = sc.hour_utc(idx)
        f["dow"] = idx.dayofweek.to_numpy().astype(float)
        f["atr_pts"] = a14 / c * 1000.0
    f["_atr"] = a14
    return {k: np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0) if not k.startswith("_") else x for k, x in f.items()}


FEATURE_NAMES: List[str] = []


def _feature_names() -> List[str]:
    global FEATURE_NAMES
    if not FEATURE_NAMES:
        n = 400
        i = pd.date_range("2024-01-01", periods=n, freq="15min")
        r = np.random.default_rng(0).normal(0, 1, n).cumsum() + 2000
        b = sc.Bars(i, r, r + 1, r - 1, r + 0.1, np.ones(n))
        FEATURE_NAMES = sorted(k for k in build_features(b, i) if not k.startswith("_"))
    return FEATURE_NAMES


# genom: (dir, sl, rr, hold, ((feature, op, qi), ...)); op: 1 -> ">", -1 -> "<"
Genome = Tuple[int, float, float, int, Tuple[Tuple[str, int, int], ...]]


class Engine:
    name = NAME
    lookback = LOOKBACK

    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.rules: List[Dict[str, Any]] = []
        self.validated = False
        self.rng = np.random.default_rng(cfg.seed)

    # ------------------------------------------------------------ holat
    def ready(self) -> bool:
        return bool(self.rules)

    def describe(self) -> str:
        if not self.rules:
            return "(qoida yo'q)"
        out = []
        for r in self.rules:
            cs = " VA ".join("%s %s %.3f" % (c["f"], ">" if c["op"] > 0 else "<", c["thr"]) for c in r["conds"])
            out.append("%s: %s | SL %.2f×ATR, TP %.2f×ATR, ushlash %d sham" % (
                "BUY" if r["dir"] > 0 else "SELL", cs, r["sl"], r["sl"] * r["rr"], r["hold"]))
        return "\n".join(out)

    def state(self) -> Dict[str, Any]:
        return {"rules": self.rules, "validated": self.validated}

    def load_state(self, d: Dict[str, Any]) -> None:
        self.rules = d.get("rules", [])
        self.validated = bool(d.get("validated"))

    def save(self) -> None:
        sc.state_path(self.cfg, "genetic_strategy.json").write_text(
            json.dumps(self.state(), ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self) -> bool:
        p = sc.state_path(self.cfg, "genetic_strategy.json")
        if p.exists():
            try:
                self.load_state(json.loads(p.read_text(encoding="utf-8")))
                return self.ready()
            except Exception:  # noqa: BLE001
                return False
        return False

    # ------------------------------------------------------------ jonli signal
    def signal(self, df: pd.DataFrame) -> Optional[sc.Signal]:
        if not self.rules or len(df) < sc.WARMUP:
            return None
        b = sc.Bars.of(df)
        f = build_features(b, df.index)
        a = f["_atr"][-1]
        for r in self.rules:
            if all((f[c["f"]][-1] > c["thr"]) if c["op"] > 0 else (f[c["f"]][-1] < c["thr"]) for c in r["conds"]):
                return sc.Signal(r["dir"], r["sl"] * a, r["sl"] * r["rr"] * a, r["hold"], "gen")
        return None

    # ------------------------------------------------------------ o'rganish
    def learn(self, hist: pd.DataFrame, budget: Optional[float] = None, pop: int = 80, max_gen: int = 80,
              progress=None) -> sc.Report:
        t0 = time.time()
        budget = self.cfg.budget_sec if budget is None else budget
        cfg = self.cfg
        b = sc.Bars.of(hist)
        F = build_features(b, hist.index)
        atr = F["_atr"]
        names = _feature_names()
        n = len(b)
        seg = sc.split_ranges(n)
        tr0, tr1 = seg["train"]
        min_n = 80
        # chegaralar: faqat train kvantillaridan
        TH = {f: np.quantile(F[f][max(tr0, sc.WARMUP):tr1], QGRID) for f in names}
        rng = self.rng
        cache: Dict[Genome, Tuple[float, Any]] = {}
        evals = [0]
        sp, sj = cfg.spread, cfg.slippage

        def mask_of(g: Genome, lo: int, hi: int) -> np.ndarray:
            m = np.zeros(n, dtype=bool)
            m[max(lo, sc.WARMUP):hi] = True
            for f, op, qi in g[4]:
                x = F[f]
                m &= (x > TH[f][qi]) if op > 0 else (x < TH[f][qi])
            return m

        def trades_of(g: Genome, lo: int, hi: int) -> sc.Trades:
            idx = np.nonzero(mask_of(g, lo, hi))[0]
            if len(idx) == 0 or len(idx) > 25000:
                return sc.Trades.empty()
            d, slm, rr, hd, _ = g
            return sc.simulate(b, idx, d, slm * atr[idx], slm * rr * atr[idx], hd, sp, sj, lo=lo, hi=hi)

        def fitness(g: Genome) -> float:
            if g in cache:
                return cache[g][0]
            evals[0] += 1
            t = trades_of(g, tr0, tr1)
            s = sc.consistent_score(t, tr0, tr1, min_n)
            cache[g] = (s, None)
            return s

        def rand_cond() -> Tuple[str, int, int]:
            return (names[rng.integers(len(names))], int(rng.choice([-1, 1])), int(rng.integers(2, len(QGRID) - 2)))

        def rand_genome() -> Genome:
            k = int(rng.integers(1, MAX_CONDS + 1))
            return (int(rng.choice([-1, 1])), float(rng.choice(SL_GRID)), float(rng.choice(RR_GRID)),
                    int(rng.choice(HOLD_GRID)), tuple(rand_cond() for _ in range(k)))

        def mutate(g: Genome) -> Genome:
            d, slm, rr, hd, cs = g
            cs = list(cs)
            r = rng.random()
            if r < 0.30 and cs:
                i = int(rng.integers(len(cs)))
                f, op, qi = cs[i]
                cs[i] = (f, op, int(np.clip(qi + rng.integers(-3, 4), 0, len(QGRID) - 1)))
            elif r < 0.42 and cs:
                i = int(rng.integers(len(cs)))
                f, op, qi = cs[i]
                cs[i] = (f, -op, qi)
            elif r < 0.56 and cs:
                cs[int(rng.integers(len(cs)))] = rand_cond()
            elif r < 0.66 and len(cs) < MAX_CONDS:
                cs.append(rand_cond())
            elif r < 0.74 and len(cs) > 1:
                cs.pop(int(rng.integers(len(cs))))
            elif r < 0.82:
                slm = float(rng.choice(SL_GRID))
            elif r < 0.90:
                rr = float(rng.choice(RR_GRID))
            elif r < 0.95:
                hd = int(rng.choice(HOLD_GRID))
            else:
                d = -d
            return (d, slm, rr, hd, tuple(cs))

        def cross(a: Genome, bb: Genome) -> Genome:
            pool = list(a[4]) + list(bb[4])
            k = int(rng.integers(1, min(MAX_CONDS, len(pool)) + 1))
            sel = [pool[i] for i in rng.permutation(len(pool))[:k]]
            pa = a if rng.random() < 0.5 else bb
            pb = a if rng.random() < 0.5 else bb
            return (pa[0], pa[1], pb[2], pb[3], tuple(sel))

        popl = [rand_genome() for _ in range(pop)]
        best = -9.0
        gen = 0
        while gen < max_gen and time.time() - t0 < budget * 0.8:
            sc_ = np.array([fitness(g) for g in popl])
            order = np.argsort(-sc_)
            if sc_[order[0]] > best:
                best = float(sc_[order[0]])
            if progress:
                progress(gen, best, evals[0])
            elite = [popl[i] for i in order[: max(4, pop // 10)]]
            nxt = list(elite)
            while len(nxt) < pop:
                r = rng.random()
                if r < 0.10:
                    nxt.append(rand_genome())
                    continue
                i1 = max(rng.integers(0, pop, 3), key=lambda i: sc_[i])
                i2 = max(rng.integers(0, pop, 3), key=lambda i: sc_[i])
                child = cross(popl[i1], popl[i2]) if r < 0.65 else popl[i1]
                nxt.append(mutate(child) if rng.random() < 0.8 else child)
            popl = nxt
            gen += 1

        # --- nomzodlar: train bo'yicha eng yaxshi 40 ta
        ranked = sorted(((s, g) for g, (s, _) in cache.items() if s > 0), key=lambda x: -x[0])[:40]
        v0, v1 = seg["val"]
        scored: List[Tuple[float, Genome, sc.Trades]] = []
        for s_tr, g in ranked:
            tv = trades_of(g, v0, v1)
            sv = sc.stats(tv)
            if sv["n"] >= 15 and sv["exp"] > 0:
                scored.append((sv["t"] + 0.25 * s_tr, g, tv))
        scored.sort(key=lambda x: -x[0])
        # --- xilma-xil ansambl (signal kesishuvi kam bo'lgan qoidalar)
        chosen: List[Genome] = []
        masks: List[np.ndarray] = []
        for _, g, _t in scored:
            m = mask_of(g, tr0, seg["val"][1])
            if all((m & mm).sum() / max(1, (m | mm).sum()) < 0.35 for mm in masks):
                chosen.append(g)
                masks.append(m)
            if len(chosen) >= 3:
                break

        rep = sc.Report(mode=NAME, evals=evals[0])
        rep.extra = {"generations": gen, "candidates": len(ranked), "val_passed": len(scored), "best_train_t": round(best, 2)}
        if not chosen:
            rep.seconds = time.time() - t0
            rep.summary = "validatsiyadan o'tgan qoida topilmadi (%d ta genom tekshirildi)" % evals[0]
            rep.reasons = ["train/validatsiya bo'yicha foydali qoida yo'q"]
            return rep

        def ens_trades(lo: int, hi: int) -> sc.Trades:
            idxs, ds, sls, tps, hds = [], [], [], [], []
            for g in chosen:
                ix = np.nonzero(mask_of(g, lo, hi))[0]
                idxs.append(ix)
                ds.append(np.full(len(ix), g[0]))
                sls.append(g[1] * atr[ix])
                tps.append(g[1] * g[2] * atr[ix])
                hds.append(np.full(len(ix), g[3]))
            return sc.simulate(b, np.concatenate(idxs), np.concatenate(ds), np.concatenate(sls), np.concatenate(tps),
                               np.concatenate(hds), sp, sj, lo=lo, hi=hi)

        res = {k: ens_trades(*seg[k]) for k in ("train", "val", "test")}
        rep.segments = {k: sc.stats(res[k]) for k in res}
        te0, te1 = seg["test"]
        ok, why = sc.gate(cfg, rep.segments, sc.chunk_exps(res["test"], te0, te1, 4))
        rep.ok, rep.reasons = ok, why
        rules = []
        for g in chosen:
            rules.append({"dir": g[0], "sl": g[1], "rr": g[2], "hold": g[3],
                          "conds": [{"f": f, "op": op, "thr": float(TH[f][qi])} for f, op, qi in g[4]]})
        cand = Engine(cfg)
        cand.rules, cand.validated = rules, ok
        rep.strategy = cand.describe()
        keep = ok or (cfg.require_pass is False and not self.rules)
        if keep:
            self.rules, self.validated = rules, ok
            self.save()
            rep.deployed = True
        rep.seconds = time.time() - t0
        rep.summary = "%d avlod, %d genom; ansambl %d qoida" % (gen, evals[0], len(chosen))
        return rep
