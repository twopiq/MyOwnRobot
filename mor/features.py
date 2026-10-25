"""Bozor holati belgilari. Hammasi ATR ga nisbatan (instrumentdan mustaqil) va shamning YOPILISHIGACHA bo'lgan ma'lumotdan
hisoblanadi — kelajakka qaramaydi."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

FEATURES: List[Tuple[str, str]] = [
    ("ret1", "1 shamlik o'zgarish"), ("ret3", "3 shamlik o'zgarish"), ("ret6", "6 shamlik o'zgarish"),
    ("ret12", "12 shamlik o'zgarish"), ("ret24", "24 shamlik o'zgarish"),
    ("ema20", "EMA20 dan masofa"), ("ema50", "EMA50 dan masofa"), ("slope", "EMA20 qiyaligi"),
    ("rsi", "RSI"), ("atr_ratio", "volatillik (ATR14/ATR100)"), ("bb", "Bollinger ichidagi o'rin"),
    ("range48", "48 shamlik diapazondagi o'rin"), ("vol", "hajm (o'rtachaga nisbatan)"),
    ("hour_sin", "kun vaqti (sin)"), ("hour_cos", "kun vaqti (cos)"), ("dow", "hafta kuni"),
    ("spread", "spred / ATR"), ("news_next", "keyingi yangilikkacha vaqt"), ("news_prev", "oxirgi yangilikdan beri vaqt"),
    ("body", "sham tanasi"), ("wick_up", "yuqori soya"), ("wick_dn", "pastki soya"),
]
NAMES = [n for n, _ in FEATURES]
LABELS = dict(FEATURES)
N_FEATURES = len(FEATURES)
POS_FEATURES = 4          # pozitsiya holati: yo'nalish, joriy R, ushlash vaqti, SL gacha masofa
WARMUP = 120


def ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def _rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    return 100.0 - 100.0 / (1.0 + up / np.maximum(dn, 1e-12))


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.empty_like(x)
    out[:k] = x[0]
    out[k:] = x[:-k]
    return out


def news_features(ts: np.ndarray, event_ts: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Eng yaqin keyingi/oldingi yuqori ta'sirli yangilikkacha vaqt (log shkala, 0..1). Ma'lumot yo'q bo'lsa — neytral 1.0."""
    if event_ts is None or len(event_ts) == 0:
        return np.ones(len(ts)), np.ones(len(ts))
    ev = np.sort(np.asarray(event_ts, dtype=np.int64))
    i = np.searchsorted(ev, ts, side="right")
    nxt = np.where(i < len(ev), ev[np.minimum(i, len(ev) - 1)] - ts, 10**9) / 60.0
    prv = np.where(i > 0, ts - ev[np.maximum(i - 1, 0)], 10**9) / 60.0
    sc = np.log1p(1440.0)
    return np.minimum(np.log1p(np.maximum(nxt, 0)) / sc, 1.0), np.minimum(np.log1p(np.maximum(prv, 0)) / sc, 1.0)


def build_features(df: pd.DataFrame, event_ts: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Qaytaradi: X [n, N_FEATURES] float32 va atr14 [n]. df: UTC indeksli open/high/low/close/volume/spread."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))
    sp = df["spread"].to_numpy(float) if "spread" in df else np.zeros(len(df))
    a = np.maximum(atr(h, l, c, 14), 1e-9)
    a100 = np.maximum(pd.Series(a).rolling(100, min_periods=1).mean().to_numpy(), 1e-9)
    cl = lambda x, k: np.clip(x, -k, k)  # noqa: E731
    f = {}
    for k in (1, 3, 6, 12, 24):
        f["ret%d" % k] = cl((c - _shift(c, k)) / a, 5.0)
    e20, e50 = ema(c, 20), ema(c, 50)
    f["ema20"], f["ema50"] = cl((c - e20) / a, 8.0), cl((c - e50) / a, 8.0)
    f["slope"] = cl((e20 - _shift(e20, 5)) / a, 3.0)
    f["rsi"] = (_rsi(c) - 50.0) / 50.0
    f["atr_ratio"] = cl(a / a100 - 1.0, 2.0)
    s = pd.Series(c)
    m20, sd20 = s.rolling(20, min_periods=1).mean().to_numpy(), s.rolling(20, min_periods=2).std().fillna(0).to_numpy()
    f["bb"] = cl((c - m20) / np.maximum(2.0 * sd20, 1e-9), 3.0)
    hh, ll = s.rolling(48, min_periods=1).max().to_numpy(), s.rolling(48, min_periods=1).min().to_numpy()
    f["range48"] = 2.0 * (c - ll) / np.maximum(hh - ll, 1e-9) - 1.0
    vm = pd.Series(v).rolling(50, min_periods=1).mean().to_numpy()
    f["vol"] = cl(np.where(vm > 0, v / np.maximum(vm, 1e-12) - 1.0, 0.0), 3.0)
    idx = pd.DatetimeIndex(df.index)
    hr = idx.hour.to_numpy() + idx.minute.to_numpy() / 60.0
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    f["dow"] = (idx.dayofweek.to_numpy() - 2.0) / 2.0
    f["spread"] = cl(sp / a * 5.0, 5.0)
    ts = np.asarray(idx.as_unit("s").asi8)
    f["news_next"], f["news_prev"] = news_features(ts, event_ts)
    top, bot = np.maximum(o, c), np.minimum(o, c)
    f["body"] = cl((c - o) / a, 4.0)
    f["wick_up"] = cl((h - top) / a, 4.0)
    f["wick_dn"] = cl((bot - l) / a, 4.0)
    X = np.column_stack([f[n] for n in NAMES]).astype(np.float32)
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), a
