"""Rejim 3 · ML — tarixdan kirish signalini bashorat qiluvchi model (XGBoost) o'rgatadi.

Yorliq (label): har sham uchun "shu yerdan BUY (yoki SELL) qilsak, xarajatlardan keyin TP SL dan oldin tegadimi?"
(uchlik to'siq — triple barrier — o'sha simulyator bilan, spred va sirpanish hisobga olingan).
Ikkita model: BUY ehtimoli va SELL ehtimoli. Ehtimollik chegarasi validatsiyada tanlanadi, oxirgi tegilmagan
holdout'da tekshiriladi. Darvozadan o'tsa model BARCHA tarixda qayta o'rgatilib (xuddi shu giperparametrlar) joblib
faylga saqlanadi va jonli savdoga beriladi.

Bu fayl faqat sl_core dan foydalanadi (boshqa dvigatellarni import qilmaydi).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sl_core as sc

NAME = "ml"
LOOKBACK = 700
THR_GRID = [round(x, 3) for x in np.arange(0.38, 0.72, 0.02)]


def build_features(b: sc.Bars, idx: pd.DatetimeIndex) -> Tuple[np.ndarray, List[str], np.ndarray]:
    o, h, l, c, v = b.o, b.h, b.l, b.c, b.v
    a14, a100 = sc.atr(h, l, c, 14), sc.atr(h, l, c, 100)
    cols: Dict[str, np.ndarray] = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for k in (1, 2, 3, 5, 10, 20, 48):
            cols[f"ret{k}"] = (c - sc.shift(c, k)) / a14
        for n in (10, 20, 50, 100, 200):
            cols[f"ema{n}_dist"] = (c - sc.ema(c, n)) / a14
        e20, e50 = sc.ema(c, 20), sc.ema(c, 50)
        cols["ema20_slope"] = (e20 - sc.shift(e20, 5)) / a14
        cols["ema50_slope"] = (e50 - sc.shift(e50, 10)) / a14
        cols["ema20_50"] = (e20 - e50) / a14
        cols["rsi5"], cols["rsi14"] = sc.rsi(c, 5), sc.rsi(c, 14)
        cols["bb_z20"] = (c - sc.sma(c, 20)) / sc.rstd(c, 20)
        cols["bb_z50"] = (c - sc.sma(c, 50)) / sc.rstd(c, 50)
        cols["atr_ratio"] = a14 / a100
        cols["atr_pts"] = a14 / c * 1000.0
        for sh in (0, 1, 2):
            cols[f"body_{sh}"] = sc.shift((c - o) / a14, sh)
            cols[f"range_{sh}"] = sc.shift((h - l) / a14, sh)
            cols[f"uw_{sh}"] = sc.shift((h - np.maximum(o, c)) / a14, sh)
            cols[f"lw_{sh}"] = sc.shift((np.minimum(o, c) - l) / a14, sh)
        for n in (20, 50):
            hh, ll = sc.rmax(h, n), sc.rmin(l, n)
            cols[f"don_pos{n}"] = (c - ll) / (hh - ll)
            cols[f"brk_hi{n}"] = (c - sc.shift(hh, 1)) / a14
            cols[f"brk_lo{n}"] = (sc.shift(ll, 1) - c) / a14
        hh14, ll14 = sc.rmax(h, 14), sc.rmin(l, 14)
        cols["stoch14"] = 100.0 * (c - ll14) / (hh14 - ll14)
        cols["vol_ratio"] = v / sc.sma(v, 50)
        hr = sc.hour_utc(idx)
        cols["hour_sin"], cols["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
        cols["dow"] = idx.dayofweek.to_numpy().astype(float)
    names = sorted(cols)
    X = np.column_stack([np.nan_to_num(cols[k], nan=0.0, posinf=0.0, neginf=0.0) for k in names]).astype(np.float32)
    return X, names, a14


DEFAULT_HP = {"max_depth": 3, "learning_rate": 0.03, "min_child_weight": 80}
# urinishlar bo'yicha qidiriladigan variantlar (1-urinish — standart qiymatlar)
SL_GRID = [1.0, 1.5, 2.0, 2.5]
RR_GRID = [1.0, 1.5, 2.0, 3.0]
HOLD_GRID = [16, 32, 48, 96]
HP_GRID = {"max_depth": [2, 3, 4], "learning_rate": [0.02, 0.03, 0.05], "min_child_weight": [40, 80, 160]}


def attempt_config(cfg: sc.Cfg, sl: float, rr: float, hold: int) -> Tuple[float, float, int, Dict[str, Any]]:
    """1-urinish: berilgan (env) qiymatlar; keyingilari: seed bo'yicha yangi SL/RR/ushlash va model parametrlari.
    Shu tufayli qayta o'rganish har safar boshqa variantni sinaydi (bir xil natija takrorlanmaydi)."""
    if cfg.attempt <= 0:
        return sl, rr, hold, dict(DEFAULT_HP)
    r = np.random.default_rng(cfg.seed)
    hp = {k: v[int(r.integers(len(v)))] for k, v in HP_GRID.items()}
    return (float(SL_GRID[int(r.integers(len(SL_GRID)))]), float(RR_GRID[int(r.integers(len(RR_GRID)))]),
            int(HOLD_GRID[int(r.integers(len(HOLD_GRID)))]), hp)


OBJECTIVES = ["classify", "weighted"]


def objective_for(cfg: sc.Cfg) -> str:
    """SL_ML_OBJECTIVE: classify | weighted | auto (auto: urinishlar bo'yicha navbatma-navbat)."""
    o = sc.env_s("SL_ML_OBJECTIVE", "auto").lower()
    if o in OBJECTIVES:
        return o
    return OBJECTIVES[max(0, cfg.attempt) % len(OBJECTIVES)]


def _new_model(seed: int, hp: Optional[Dict[str, Any]] = None):
    hp = {**DEFAULT_HP, **(hp or {})}
    try:
        import xgboost as xgb
        return xgb.XGBClassifier(n_estimators=250, max_depth=hp["max_depth"], learning_rate=hp["learning_rate"],
                                 subsample=0.7, colsample_bytree=0.7, min_child_weight=hp["min_child_weight"],
                                 reg_lambda=10.0, n_jobs=2, tree_method="hist", random_state=seed,
                                 eval_metric="logloss", verbosity=0), "xgboost"
    except Exception:  # noqa: BLE001
        pass
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_depth=hp["max_depth"], learning_rate=hp["learning_rate"] * 1.6,
                                              max_iter=200, min_samples_leaf=hp["min_child_weight"] * 2.5,
                                              l2_regularization=10.0, random_state=seed), "sklearn"
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("ML rejimi uchun xgboost yoki scikit-learn kerak (setup_bot_env.bat ni ishga tushiring): %s" % e)


class Engine:
    name = NAME
    lookback = LOOKBACK

    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.sl = sc.env_f("SL_ML_SL", 1.5)
        self.rr = sc.env_f("SL_ML_RR", 1.5)
        self.hold = sc.env_i("SL_ML_HOLD", 32)
        self.models: Dict[str, Any] = {}
        self.thr = 0.0
        self.feat_names: List[str] = []
        self.validated = False
        self.kind = ""

    def ready(self) -> bool:
        return bool(self.models) and self.thr > 0

    def describe(self) -> str:
        if not self.ready():
            return "(model yo'q)"
        return "%s: BUY/SELL ehtimol ≥ %.2f | SL %.2f×ATR, TP %.2f×ATR, ushlash %d sham | %d xususiyat" % (
            self.kind, self.thr, self.sl, self.sl * self.rr, self.hold, len(self.feat_names))

    def save(self) -> None:
        import joblib
        joblib.dump({"models": self.models, "thr": self.thr, "feat": self.feat_names, "sl": self.sl, "rr": self.rr,
                     "hold": self.hold, "validated": self.validated, "kind": self.kind},
                    sc.state_path(self.cfg, "ml_model.joblib"))

    def load(self) -> bool:
        p = sc.state_path(self.cfg, "ml_model.joblib")
        if not p.exists():
            return False
        try:
            import joblib
            d = joblib.load(p)
            self.models, self.thr, self.feat_names = d["models"], d["thr"], d["feat"]
            self.sl, self.rr, self.hold = d["sl"], d["rr"], d["hold"]
            self.validated, self.kind = bool(d.get("validated")), d.get("kind", "")
        except Exception as e:  # noqa: BLE001
            sc.log("ml model yuklanmadi: %s" % e)
            return False
        return self.ready()

    def _proba(self, models: Dict[str, Any], X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        return models["long"].predict_proba(X)[:, 1], models["short"].predict_proba(X)[:, 1]

    # ------------------------------------------------------------ jonli signal
    def signal(self, df: pd.DataFrame) -> Optional[sc.Signal]:
        if not self.ready() or len(df) < sc.WARMUP:
            return None
        b = sc.Bars.of(df)
        X, names, a14 = build_features(b, df.index)
        if names != self.feat_names:
            return None
        pl, ps = self._proba(self.models, X[-1:])
        p, d = (float(pl[0]), 1) if pl[0] >= ps[0] else (float(ps[0]), -1)
        if p < self.thr:
            return None
        return sc.Signal(d, self.sl * a14[-1], self.sl * self.rr * a14[-1], self.hold, "ml%.2f" % p)

    # ------------------------------------------------------------ mustahkamlik
    def _walk_forward(self, b, X, a14, rows, fit, trades_at, thr, seg, n, hold_m):
        """Holdout'dan o'tgan modelni yana bir bor tekshiradi: oxirgi 50% tarixni 5 bo'lakka bo'lib, har bo'lak uchun
        faqat undan OLDINGI ma'lumotda qayta o'rgatadi va bo'lakda savdo qiladi. Kamida 60% bo'lak foydali va
        umumiy kutilma > 0 bo'lishi shart (bitta holdout tasodifiga bog'liq bo'lmaslik uchun)."""
        k, start = 5, n // 2
        edges = np.linspace(start, n, k + 1).astype(int)
        exps, ns = [], []
        allR: List[np.ndarray] = []
        for i in range(k):
            lo, hi = int(edges[i]), int(edges[i + 1])
            tr_ix = rows(0, lo - hold_m - 2)
            te_ix = rows(lo, hi)
            if len(tr_ix) < 3000 or len(te_ix) < 100:
                continue
            ms, _ = fit(tr_ix)
            tt = trades_at(ms, te_ix, thr, lo, hi)
            exps.append(float(tt.R.mean()) if len(tt.R) else 0.0)
            ns.append(int(len(tt.R)))
            allR.append(np.asarray(tt.R))
        info = {"folds": [round(x, 3) for x in exps], "n": ns}
        if len(exps) < 3:
            return False, ["walk-forward uchun ma'lumot yetarli emas"], info
        pooled = np.concatenate(allR) if allR else np.zeros(0)
        pe = float(pooled.mean()) if len(pooled) else 0.0
        share = sum(1 for e in exps if e > 0) / len(exps)
        info.update({"pooled": round(pe, 3), "share": round(share, 2)})
        why = []
        if pe <= 0:
            why.append("walk-forward umumiy kutilma %.3fR ≤ 0" % pe)
        if share < 0.6:
            why.append("walk-forward bo'laklarining faqat %.0f%% foydali" % (share * 100))
        return (not why), why, info

    # ------------------------------------------------------------ o'rganish
    def learn(self, hist: pd.DataFrame, budget: Optional[float] = None, progress=None) -> sc.Report:
        t0 = time.time()
        cfg = self.cfg
        b = sc.Bars.of(hist)
        n = len(b)
        X, names, a14 = build_features(b, hist.index)
        rep = sc.Report(mode=NAME)
        sl_m, rr_m, hold_m, hp = attempt_config(cfg, self.sl, self.rr, self.hold)
        rep.extra["params"] = {"sl": sl_m, "rr": rr_m, "hold": hold_m, **hp}
        # --- yorliqlar: har sham uchun BUY va SELL natijasi (kesishuvchi bitimlarga ruxsat — bu faqat yorliq)
        allidx = np.arange(sc.WARMUP, n - hold_m - 3)
        y, yr = {}, {}
        for d, key in ((1, "long"), (-1, "short")):
            tr = sc.simulate(b, allidx, d, sl_m * a14[allidx], sl_m * rr_m * a14[allidx], hold_m,
                             cfg.spread, cfg.slippage, no_overlap=False)
            lab = np.full(n, -1, dtype=np.int8)
            lab[tr.entry_i - 1] = (tr.R > 0).astype(np.int8)
            y[key] = lab
            rr_arr = np.zeros(n, dtype=np.float32)
            rr_arr[tr.entry_i - 1] = tr.R
            yr[key] = rr_arr
        seg = sc.split_ranges(n)
        emb = hold_m + 2

        def rows(lo: int, hi: int) -> np.ndarray:
            r = np.arange(max(lo, sc.WARMUP), hi - emb)
            return r[(y["long"][r] >= 0) & (y["short"][r] >= 0)]

        tr_r, va_r, te_r = rows(*seg["train"]), rows(*seg["val"]), rows(*seg["test"])
        if len(tr_r) < 3000 or len(va_r) < 800:
            rep.summary = "tarix qisqa (train %d, val %d qator)" % (len(tr_r), len(va_r))
            rep.reasons = [rep.summary]
            return rep

        objective = objective_for(cfg)
        rep.extra["objective"] = objective

        def fit(rr_: np.ndarray) -> Tuple[Dict[str, Any], str]:
            ms, kind = {}, ""
            for key in ("long", "short"):
                m, kind = _new_model(cfg.seed, hp)
                if objective == "weighted":      # katta zarar/foyda ko'proq "jazo/mukofot" oladi
                    m.fit(X[rr_], y[key][rr_], sample_weight=np.clip(np.abs(yr[key][rr_]), 0.2, 3.0) + 0.0)
                else:
                    m.fit(X[rr_], y[key][rr_])
                ms[key] = m
            return ms, kind

        models, kind = fit(tr_r)
        if progress:
            progress("fit", 1, 1, 0.0)

        def trades_at(ms: Dict[str, Any], r: np.ndarray, thr: float, lo: int, hi: int) -> sc.Trades:
            pl, ps = self._proba(ms, X[r])
            p = np.maximum(pl, ps)
            d = np.where(pl >= ps, 1, -1)
            m = p >= thr
            ix = r[m]
            return sc.simulate(b, ix, d[m], sl_m * a14[ix], sl_m * rr_m * a14[ix], hold_m, cfg.spread,
                               cfg.slippage, lo=lo, hi=hi)

        # --- chegara: validatsiyada
        best_thr, best_t, best_s = 0.0, -99.0, None
        v0, v1 = seg["val"]
        for thr in THR_GRID:
            tv = trades_at(models, va_r, thr, v0, v1)
            s = sc.stats(tv)
            if s["n"] >= 25 and s["exp"] > 0 and s["t"] > best_t:
                best_thr, best_t, best_s = thr, s["t"], s
        rep.evals = len(THR_GRID)
        te0, te1 = seg["test"]
        # xususiyat muhimligi (tushuntirish uchun)
        try:
            imp = models["long"].feature_importances_
            rep.extra["top_features"] = [names[i] for i in np.argsort(-imp)[:6]]
        except Exception:  # noqa: BLE001
            pass
        rep.extra["model"] = kind
        if best_s is None:
            rep.segments = {"train": sc.stats(trades_at(models, tr_r, 0.5, *seg["train"])),
                            "val": sc.stats(trades_at(models, va_r, 0.5, v0, v1))}
            rep.reasons = ["validatsiyada foydali ehtimol chegarasi topilmadi (model validatsiyada ustunlik bermadi)"]
            rep.summary = "model o'rgatildi, lekin validatsiyada ustunlik yo'q"
            rep.seconds = time.time() - t0
            return rep
        res = {"train": trades_at(models, tr_r, best_thr, *seg["train"]), "val": trades_at(models, va_r, best_thr, v0, v1),
               "test": trades_at(models, te_r, best_thr, te0, te1)}
        rep.segments = {k: sc.stats(v) for k, v in res.items()}
        ok, why = sc.gate(cfg, rep.segments, sc.chunk_exps(res["test"], te0, te1, 4), rep=rep)
        rep.curves = sc.curves_of(res, hist.index)
        if ok:
            wf_ok, wf_why, wf = self._walk_forward(b, X, a14, rows, fit, trades_at, best_thr, seg, n, hold_m)
            rep.extra["walk_forward"] = wf
            if not wf_ok:
                ok, why = False, why + wf_why
        conf = sc.make_confirm(cfg)
        if ok and conf:
            def _ev(d, sp_, sj_):
                Xd, nd, ad = build_features(sc.Bars.of(d), d.index)
                bd = sc.Bars.of(d)
                pl, ps = self._proba(models, Xd)
                p = np.maximum(pl, ps)
                dd = np.where(pl >= ps, 1, -1)
                ix = np.nonzero(p >= best_thr)[0]
                return sc.simulate(bd, ix, dd[ix], sl_m * ad[ix], sl_m * rr_m * ad[ix], hold_m, sp_, sj_)
            ok2, why2, info = conf(_ev)
            ok, why = ok and ok2, why + why2
            rep.extra["confirm"] = info
        rep.ok, rep.reasons = ok, why
        keep = ok or (not cfg.require_pass and not self.ready())
        if keep:
            all_r = rows(0, n)
            ms, kind = fit(all_r)                 # barcha tarixda qayta o'rgatish (giperparametr va chegara o'zgarmaydi)
            self.models, self.thr, self.feat_names, self.kind, self.validated = ms, best_thr, names, kind, ok
            self.sl, self.rr, self.hold = sl_m, rr_m, hold_m
            self.save()
            rep.deployed = True
        rep.strategy = "%s: ehtimol ≥ %.2f | SL %.2f×ATR, TP %.2f×ATR, %d sham" % (kind, best_thr, sl_m, sl_m * rr_m, hold_m)
        rep.seconds = time.time() - t0
        rep.summary = "model: %s, chegara %.2f" % (kind, best_thr)
        return rep
