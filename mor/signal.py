"""Signal tekshiruvi: o'qitishdan OLDIN ma'lumotda kelajak narxni bashorat qiladigan narsa bormi?

Oddiy (chiziqli, ridge) model O'RGANISH davrida o'rgatiladi va ko'rilmagan davrlarda (val, test) kelajak harakat (ATR birligida)
bilan taqqoslanadi. Korrelyatsiya ~0 bo'lsa — RL ham bu ma'lumotdan hech narsa o'rgana olmaydi: xotira to'lib borsa ham natija
yaxshilanmaydi. Xarajat (spred + sirpanish) bitimga necha R ekanini ham ko'rsatadi: signal shundan kuchliroq bo'lishi kerak.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np

from . import features as F
from .env import EnvCfg, Series

HORIZONS = (4, 16)
STRONG, WEAK = 0.05, 0.02


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 50 or a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def check_series(s: Series, cfg: EnvCfg | None = None) -> Dict[str, Any]:
    cfg = cfg or EnvCfg()
    n = len(s)
    cost = (s.spread + 2 * cfg.slippage_atr * s.atr) / (cfg.sl_atr * np.maximum(s.atr, 1e-12))
    tr0, tr1 = s.bounds["train"]
    va0, va1 = s.bounds["val"]
    te0, te1 = s.bounds["test"]
    best = {"h": 0, "val": -9.0, "test": 0.0}
    for h in HORIZONS:
        fwd = np.full(n, np.nan)
        fwd[:-h] = (s.c[h:] - s.c[:-h]) / np.maximum(s.atr[:-h], 1e-12)
        A = np.c_[s.X[tr0:tr1 - h], np.ones(tr1 - h - tr0)]
        w = np.linalg.solve(A.T @ A + 10.0 * np.eye(A.shape[1]), A.T @ fwd[tr0:tr1 - h])

        def pc(p, q):
            q = q - h if q == n else q
            return _corr(np.c_[s.X[p:q], np.ones(q - p)] @ w, fwd[p:q])
        v, t = pc(va0, va1), pc(te0, te1)
        if min(v, t) > min(best["val"], best["test"]) if best["h"] else True:
            best = {"h": h, "val": v, "test": t}
    m = min(best["val"], best["test"])
    verdict = "bor" if m >= STRONG else ("zaif" if m >= WEAK else "yo'q")
    news = float(np.std(s.X[tr0:tr1, F.NAMES.index("news_next")])) > 1e-9
    return {"symbol": s.symbol, "tf": s.tf, "bars": n, "cost_r": float(np.median(cost[tr0:tr1])), "h": best["h"],
            "val_corr": best["val"], "test_corr": best["test"], "verdict": verdict, "news": news}


def check_all(series: Sequence[Series], cfg: EnvCfg | None = None) -> List[Dict[str, Any]]:
    return [check_series(s, cfg) for s in series]


def advice(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "Tekshirish uchun dataset yo'q."
    if all(r["verdict"] == "yo'q" for r in rows):
        return ("Bu ma'lumotda kelajak narxni bashorat qiladigan signal topilmadi — o'qitish natijani yaxshilamaydi. "
                "Yangi ma'lumot qo'shing (kalendar, boshqa bozorlar) yoki kamroq, tanlab savdo qiling.")
    if any(r["verdict"] == "bor" for r in rows):
        return "Ba'zi instrumentlarda signal bor — o'qitishga arziydi (baribir test natijasi hal qiladi)."
    return "Signal zaif: xarajatdan oshishi mumkin emas. Yangi ma'lumot qo'shib qayta tekshiring."
