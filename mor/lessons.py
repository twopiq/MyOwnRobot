"""Qonuniyat qidirish: tajriba xotirasidagi bitimlardan "qaysi sharoitda yutadi/yutqazadi" qoidalarini topadi.

Jarayon (haddan tashqari moslashishga qarshi):
 1. O'RGANISH davri bitimlarida bir va ikki shartli qoidalar sinab ko'riladi (belgilar kvantillari bo'yicha);
 2. kuchli nomzodlar (|t| yuqori, bitim soni yetarli) saqlanadi;
 3. har bir nomzod O'RGANILMAGAN davr (validatsiya + test) bitimlarida qayta tekshiriladi:
    belgisi bir xil va statistik jihatdan hech bo'lmasa ishonchli bo'lsa — "tasdiqlangan", aks holda "rad etilgan".
Tasdiqlangan "qochish" qoidalari (avoid) agent kirishini to'sadi (Guard).
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import features as F


@dataclass
class MineCfg:
    min_n: int = 60              # o'rganish davrida eng kam bitim
    t_min: float = 3.5           # nomzod uchun |t| (ko'p sinov tufayli qattiq)
    oos_min_n: int = 30
    oos_t_min: float = 1.65      # tasdiqlash: bir tomonlama ~5%
    top_singles: int = 40
    max_lessons: int = 12
    quantiles: Tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)


def _stat(r: np.ndarray) -> Tuple[int, float, float]:
    n = len(r)
    if n < 2:
        return n, float(r.mean()) if n else 0.0, 0.0
    sd = r.std(ddof=1)
    return n, float(r.mean()), float(r.mean() / (sd / np.sqrt(n))) if sd > 1e-12 else 0.0


def _mask(X: np.ndarray, side: np.ndarray, rule: Dict[str, Any]) -> np.ndarray:
    m = np.ones(len(X), bool)
    if rule["side"] != 0:
        m &= side == rule["side"]
    for c in rule["clauses"]:
        col = X[:, c["f"]]
        m &= (col <= c["v"]) if c["op"] == "<=" else (col > c["v"])
    return m


def rule_text(rule: Dict[str, Any]) -> str:
    parts = []
    for c in rule["clauses"]:
        parts.append("%s %s %.2f" % (F.LABELS[F.NAMES[c["f"]]], "≤" if c["op"] == "<=" else ">", c["v"]))
    head = {1: "BUY kirishda: ", -1: "SELL kirishda: ", 0: ""}[rule["side"]]
    return head + " va ".join(parts)


def mine(train: Dict[str, np.ndarray], oos: Dict[str, np.ndarray], cfg: Optional[MineCfg] = None) -> List[Dict[str, Any]]:
    cfg = cfg or MineCfg()
    Xt, rt, st = train["X"][:, :F.N_FEATURES], train["r"], train["side"]
    Xo, ro, so = oos["X"][:, :F.N_FEATURES], oos["r"], oos["side"]
    if len(rt) < cfg.min_n * 2 or len(ro) < cfg.oos_min_n:
        return []
    thr = np.quantile(Xt, cfg.quantiles, axis=0)                      # [q, F]
    cands: List[Tuple[float, Dict[str, Any], np.ndarray]] = []
    for side in (0, 1, -1):
        base = np.ones(len(rt), bool) if side == 0 else (st == side)
        singles = []
        for j in range(F.N_FEATURES):
            for qi in range(len(cfg.quantiles)):
                v = float(thr[qi, j])
                for op in ("<=", ">"):
                    rule = {"side": side, "clauses": [{"f": j, "op": op, "v": v}]}
                    m = _mask(Xt, st, rule)
                    n, mean, t = _stat(rt[m])
                    if n >= cfg.min_n:
                        singles.append((abs(t), t, rule))
        singles.sort(key=lambda x: -x[0])
        for at, t, rule in singles:
            if at >= cfg.t_min:
                cands.append((at, rule, _mask(Xt, st, rule)))
        top = [x[2] for x in singles[:cfg.top_singles]]
        for i in range(len(top)):
            for k in range(i + 1, len(top)):
                if top[i]["clauses"][0]["f"] == top[k]["clauses"][0]["f"]:
                    continue
                rule = {"side": side, "clauses": top[i]["clauses"] + top[k]["clauses"]}
                m = _mask(Xt, st, rule)
                n, mean, t = _stat(rt[m])
                if n >= cfg.min_n and abs(t) >= cfg.t_min + 0.3:
                    cands.append((abs(t), rule, m))
    cands.sort(key=lambda x: -x[0])
    uniq, seen = [], set()
    for at, rule, m in cands:
        sig = (rule["side"], tuple(sorted((c["f"], c["op"], round(c["v"], 3)) for c in rule["clauses"])))
        if sig not in seen:
            seen.add(sig)
            uniq.append((at, rule, m))
    # tasdiqlash chegarasi sinalgan nomzodlar soniga qarab qattiqlashadi (Bonferroni, 3.0 bilan cheklangan)
    need_t = min(3.0, max(cfg.oos_t_min, NormalDist().inv_cdf(1.0 - 0.05 / max(1, len(uniq)))))
    out: List[Dict[str, Any]] = []
    for at, rule, m in uniq:
        n, mean, t = _stat(rt[m])
        mo = _mask(Xo, so, rule)
        on, omean, ot = _stat(ro[mo])
        same = (mean < 0) == (omean < 0) and on >= cfg.oos_min_n
        verified = bool(same and abs(ot) >= need_t)
        out.append({"kind": "avoid" if mean < 0 else "prefer", "text": rule_text(rule), "rule": rule, "n": n, "exp": mean,
                    "t": t, "oos_n": on, "oos_exp": omean, "oos_t": ot, "status": "verified" if verified else "rejected"})
        if len(out) >= cfg.max_lessons * 6:
            break
    ver = [x for x in out if x["status"] == "verified"]
    rej = [x for x in out if x["status"] == "rejected"][:cfg.max_lessons]
    ver.sort(key=lambda x: -abs(x["oos_t"]))
    return ver[:cfg.max_lessons] + rej


class Guard:
    """Tasdiqlangan 'qochish' qoidalari: mos kelsa kirishni to'sadi."""

    def __init__(self, lessons: List[Dict[str, Any]]):
        self.rules = [x["rule"] for x in lessons if x.get("status") == "verified" and x.get("kind") == "avoid"]

    def __len__(self) -> int:
        return len(self.rules)

    def veto(self, feat: np.ndarray, side: int) -> bool:
        if not self.rules:
            return False
        x = np.atleast_2d(feat)[:, :F.N_FEATURES]
        s = np.array([side])
        return any(bool(_mask(x, s, r)[0]) for r in self.rules)
