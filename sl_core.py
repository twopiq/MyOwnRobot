"""Self-learning robot · umumiy infratuzilma (strategiya mantig'isiz).

Bu faylda: sozlamalar (env), tarix yuklash, indikatorlar, narx xarajatini hisobga oluvchi simulyator,
metrikalar, train/val/test bo'lish, qabul darvozasi (gate) va MT5 broker qatlami.
Uchta dvigatel (sl_genetic / sl_optimizer / sl_ml) faqat shu fayldan foydalanadi va bir-birini import qilmaydi.

Ma'lumot bilan ishlash qoidalari (haddan tashqari moslashishdan himoya):
  * Signal yopilgan sham oxirida, kirish KEYINGI sham ochilishida (ask = bid + spred, + sirpanish).
  * SL va TP bir shamda tegsa — SL birinchi hisoblanadi (konservativ).
  * Bir vaqtda bitta pozitsiya (kesishuvchi bitimlar sanalmaydi).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}
MODES = ("genetic", "optimizer", "ml")
_ALIASES = {"gen": "genetic", "genetic": "genetic", "ga": "genetic", "evolution": "genetic",
            "opt": "optimizer", "optimizer": "optimizer", "optimize": "optimizer", "wfo": "optimizer",
            "ml": "ml", "ai": "ml", "xgb": "ml"}
WARMUP = 300          # indikatorlar "isishi" uchun birinchi shamlar signal bermaydi


def force_utf8_stdio() -> None:
    """stdout/stderr ni UTF-8 ga o'tkazadi. Windows'da konsol cp1252 bo'ladi va "≥", "×" kabi belgilar
    UnicodeEncodeError beradi; yig'ilgan .exe da PYTHONIOENCODING ham e'tiborsiz qoladi."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass                      # None (oynali .exe) yoki qayta sozlab bo'lmaydigan oqim


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ================================================================ sozlamalar

def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None or str(v).strip() == "" else str(v).strip()


def env_f(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)).replace(",", "."))
    except ValueError:
        return default


def env_i(name: str, default: int) -> int:
    return int(env_f(name, float(default)))


def env_b(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on", "ha")


@dataclass
class Cfg:
    mode: str = "genetic"
    symbol: str = "XAUUSD"
    tf: str = "M15"
    history: str = ""               # tarix fayli (csv/pkl/parquet); bo'sh — MT5 dan olinadi
    history_gmt: float = 0.0        # fayldagi vaqt GMT ga nisbatan (Dukascopy = 0)
    history_years: float = 0.0      # 0 = hammasi
    spread: float = 0.30            # narx birligida (XAUUSD uchun $)
    slippage: float = 0.05
    risk_pct: float = 0.5
    max_pos: int = 1
    max_spread: float = 0.80        # shu spreddan kengida yangi bitim ochilmaydi
    max_daily_loss_pct: float = 3.0
    magic: int = 26101900
    relearn_hours: float = 168.0
    budget_sec: float = 240.0       # bitta o'rganish sikli uchun vaqt
    require_pass: bool = True       # True: faqat tekshiruvdan o'tgan strategiya savdo qiladi
    demo_only: bool = True
    seed: int = 7
    state_dir: str = "state"
    terminal: str = ""              # terminal64.exe yo'li (bo'sh — MT5 kutubxonasi o'zi tanlaydi)
    portable: bool = False
    login: int = 0                  # kutilgan hisob raqami (0 — tekshirilmaydi)
    server_gmt: float = float("nan")   # MT5 server GMT (qishki) — bo'sh bo'lsa avtomatik aniqlanadi
    # --- qabul darvozasi (holdout = eng oxirgi tegilmagan davr)
    min_test_trades: int = 40
    min_exp_r: float = 0.05
    min_pf: float = 1.10
    min_t: float = 1.0
    min_pos_chunks: float = 0.5     # holdout bo'laklarining nechtasi foydali bo'lishi kerak
    # --- ko'p urinish / tasdiqlovchi instrumentlar
    repeat: int = 1                 # necha marta (yangi seed bilan) qayta o'rganib ko'riladi
    trials: int = 1                 # darvoza qattiqlashuvi uchun jami urinishlar soni
    confirm: str = ""               # "fayl|spred|sirpanish;fayl2|spred2" — boshqa instrumentlarda tasdiqlash
    # --- jonli himoya
    kill_window: int = 20           # oxirgi N jonli bitim
    kill_sum_r: float = -6.0        # yig'indi R shundan past bo'lsa — to'xtab, qayta o'rganadi

    @staticmethod
    def from_env() -> "Cfg":
        m = _ALIASES.get(_env("SL_MODE", "genetic").lower(), "")
        if not m:
            raise SystemExit("SL_MODE noto'g'ri: genetic | optimizer | ml  (berilgan: %r)" % _env("SL_MODE"))
        c = Cfg(mode=m)
        c.symbol = _env("BOT_SYMBOL", _env("SL_SYMBOL", c.symbol))
        c.tf = _env("SL_TF", c.tf).upper()
        if c.tf not in TF_MIN:
            raise SystemExit("SL_TF noto'g'ri: %s" % ", ".join(TF_MIN))
        c.history = _env("SL_HISTORY", "")
        c.history_gmt = env_f("SL_HISTORY_GMT", c.history_gmt)
        c.history_years = env_f("SL_HISTORY_YEARS", c.history_years)
        c.spread = env_f("SL_SPREAD", c.spread)
        c.slippage = env_f("SL_SLIPPAGE", c.slippage)
        c.risk_pct = env_f("SL_RISK_PCT", c.risk_pct)
        c.max_pos = max(1, env_i("SL_MAX_POS", c.max_pos))
        c.max_spread = env_f("SL_MAX_SPREAD", c.max_spread)
        c.max_daily_loss_pct = env_f("SL_MAX_DAILY_LOSS_PCT", c.max_daily_loss_pct)
        c.magic = env_i("SL_MAGIC", c.magic + MODES.index(m))
        c.relearn_hours = env_f("SL_RELEARN_HOURS", c.relearn_hours)
        c.budget_sec = env_f("SL_BUDGET_SEC", c.budget_sec)
        c.require_pass = env_b("SL_REQUIRE_PASS", c.require_pass)
        c.demo_only = env_b("SL_DEMO_ONLY", c.demo_only)
        c.seed = env_i("SL_SEED", c.seed)
        c.state_dir = _env("SL_STATE_DIR", c.state_dir)
        c.terminal = _env("SL_TERMINAL", c.terminal).strip('"')
        c.portable = env_b("SL_PORTABLE", bool(c.terminal))
        c.login = env_i("SL_LOGIN", c.login)
        sg = _env("SL_SERVER_GMT", "")
        c.server_gmt = float(sg) if sg else float("nan")
        c.min_test_trades = env_i("SL_MIN_TEST_TRADES", c.min_test_trades)
        c.min_exp_r = env_f("SL_MIN_EXP_R", c.min_exp_r)
        c.min_pf = env_f("SL_MIN_PF", c.min_pf)
        c.min_t = env_f("SL_MIN_T", c.min_t)
        c.min_pos_chunks = env_f("SL_MIN_POS_CHUNKS", c.min_pos_chunks)
        c.repeat = max(1, env_i("SL_REPEAT", c.repeat))
        c.trials = max(1, env_i("SL_TRIALS", c.trials))
        c.confirm = _env("SL_CONFIRM", c.confirm)
        c.kill_window = env_i("SL_KILL_WINDOW", c.kill_window)
        c.kill_sum_r = env_f("SL_KILL_SUM_R", c.kill_sum_r)
        return c

    @property
    def tf_min(self) -> int:
        return TF_MIN[self.tf]

    @property
    def bars_per_year(self) -> float:
        return 252 * 23 * 60 / self.tf_min


# ================================================================ vaqt zonasi (server -> UTC)

def us_dst(ts: pd.DatetimeIndex) -> np.ndarray:
    """AQSh yozgi vaqti (mart 2-yakshanba .. noyabr 1-yakshanba), kun aniqligida. MT4/MT5 server vaqti shunga bog'liq."""
    y = ts.year.to_numpy()
    out = np.zeros(len(ts), dtype=bool)
    for yy in np.unique(y):
        d = dt.date(int(yy), 3, 1)
        d += dt.timedelta(days=(6 - d.weekday()) % 7 + 7)
        s = np.datetime64(d)
        e0 = dt.date(int(yy), 11, 1)
        e0 += dt.timedelta(days=(6 - e0.weekday()) % 7)
        e = np.datetime64(e0)
        day = ts.values.astype("datetime64[D]")
        out |= (y == yy) & (day >= s) & (day < e)
    return out


def server_to_utc(ts: pd.DatetimeIndex, server_gmt_winter: float) -> pd.DatetimeIndex:
    off = server_gmt_winter + us_dst(ts).astype(float)
    return ts - pd.to_timedelta(off, unit="h")


# ================================================================ tarix

def _to_time(s: pd.Series) -> pd.DatetimeIndex:
    if pd.api.types.is_numeric_dtype(s):
        x = s.astype("int64")
        unit = "ms" if x.abs().median() > 1e11 else "s"
        return pd.DatetimeIndex(pd.to_datetime(x, unit=unit))
    return pd.DatetimeIndex(pd.to_datetime(s))


def read_history_file(path: str, gmt: float = 0.0) -> pd.DataFrame:
    """csv / pkl / parquet -> DataFrame(open, high, low, close, volume), UTC, tartiblangan."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".pkl", ".pickle"):
        df = pd.read_pickle(p)
    elif ext == ".parquet":
        df = pd.read_parquet(p)
    else:
        head = p.read_text(encoding="utf-8", errors="replace")[:4000]
        try:
            sep = csv.Sniffer().sniff(head.splitlines()[0] + "\n" + head.splitlines()[1], delimiters=",;\t").delimiter
        except Exception:  # noqa: BLE001
            sep = ","
        first = head.splitlines()[0]
        has_header = any(ch.isalpha() for ch in first.replace("e", "").replace("E", ""))
        if has_header:
            df = pd.read_csv(p, sep=sep)
        else:  # MT4 eksporti: sana, vaqt, o, h, l, c, hajm
            df = pd.read_csv(p, sep=sep, header=None)
            if df.shape[1] >= 7:
                df.columns = ["date", "time", "open", "high", "low", "close", "volume"] + list(df.columns[7:])
            else:
                df.columns = ["time", "open", "high", "low", "close", "volume"][:df.shape[1]]
    df = df.copy()
    df.columns = [str(c).strip().lower().strip("<>") for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns and "time" in df.columns and not pd.api.types.is_numeric_dtype(df["time"]):
            df.index = pd.DatetimeIndex(pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str)))
        else:
            tcol = next((c for c in ("time", "datetime", "timestamp", "date", "index") if c in df.columns), None)
            if tcol is None:
                raise ValueError("tarix faylida vaqt ustuni topilmadi")
            df.index = _to_time(df[tcol])
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    if "volume" not in df.columns:
        df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0.0
    need = ["open", "high", "low", "close"]
    if any(c not in df.columns for c in need):
        raise ValueError("ustunlar kerak: open, high, low, close")
    df = df[need + ["volume"]].astype(float)
    df.index = pd.DatetimeIndex(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=need)
    if gmt:
        df.index = df.index - pd.Timedelta(hours=gmt)
    return df


def to_tf(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Kerak bo'lsa pastroq timeframe'dan yuqoriga o'tkazadi (M1 -> M15)."""
    if len(df) < 3:
        return df
    step = float(np.median(np.diff(df.index.values[: min(len(df), 5000)]).astype("timedelta64[s]").astype(float))) / 60.0
    if step >= minutes - 1e-9:
        return df
    r = df.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return r.dropna(subset=["close"])


def limit_years(df: pd.DataFrame, years: float) -> pd.DataFrame:
    if years and years > 0 and len(df):
        return df[df.index >= df.index[-1] - pd.Timedelta(days=365.25 * years)]
    return df


# ================================================================ indikatorlar (numpy)

def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def rstd(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def rmax(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def rmin(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


def shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k > 0:
        out[k:] = x[:-k]
    elif k < 0:
        out[:k] = x[-k:]
    else:
        out[:] = x
    return out


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
        out = 100.0 - 100.0 / (1.0 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    out[(dn == 0) & (up == 0)] = 50.0
    return out


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    pc = shift(c, 1)
    pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def hour_utc(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.hour.to_numpy() + index.minute.to_numpy() / 60.0).astype(float)


@dataclass
class Bars:
    """Numpy ko'rinishidagi sham massivlari."""
    idx: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    @staticmethod
    def of(df: pd.DataFrame) -> "Bars":
        return Bars(df.index, df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float),
                    df["close"].to_numpy(float), df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df)))

    def __len__(self) -> int:
        return len(self.c)


# ================================================================ simulyator

@dataclass
class Trades:
    entry_i: np.ndarray          # kirish shami (ochilishi)
    exit_i: np.ndarray
    dirs: np.ndarray
    R: np.ndarray                # xarajatlardan keyingi natija, SL masofasi birligida
    pnl: np.ndarray              # narx birligida (1 lot/1 birlik uchun)

    @staticmethod
    def empty() -> "Trades":
        z = np.zeros(0)
        return Trades(z.astype(int), z.astype(int), z.astype(int), z, z)

    def __len__(self) -> int:
        return len(self.R)


def _sim_chunk(b: Bars, idx: np.ndarray, dirs: np.ndarray, sl: np.ndarray, tp: np.ndarray, hold: np.ndarray,
               spread: float, slip: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Signal shamlari (idx) uchun (exit_offset, pnl, R). Barcha idx uchun idx+hold < len bo'lishi shart."""
    H = int(hold.max())
    n = len(idx)
    j0 = idx + 1
    ent_bid = b.o[j0]
    long = dirs > 0
    e = np.where(long, ent_bid + spread + slip, ent_bid - slip)
    sl_p = np.where(long, e - sl, e + sl)
    tp_p = np.where(long, e + tp, e - tp)
    off = np.arange(H)[None, :]
    rows = j0[:, None] + off
    lo, hi, cl = b.l[rows], b.h[rows], b.c[rows]
    valid = off < hold[:, None]
    lg = long[:, None]
    sl_hit = np.where(lg, lo <= sl_p[:, None], hi + spread >= sl_p[:, None]) & valid
    tp_hit = np.where(lg, hi >= tp_p[:, None], lo + spread <= tp_p[:, None]) & valid
    big = H + 5
    i_sl = np.where(sl_hit.any(1), sl_hit.argmax(1), big)
    i_tp = np.where(tp_hit.any(1), tp_hit.argmax(1), big)
    # SL birinchi: teng bo'lsa SL
    use_sl = (i_sl <= i_tp) & (i_sl < big)
    use_tp = (~use_sl) & (i_tp < big)
    t_off = hold - 1
    x_off = np.where(use_sl, i_sl, np.where(use_tp, i_tp, t_off))
    c_t = cl[np.arange(n), t_off]
    exit_px = np.where(use_sl, np.where(long, sl_p - slip, sl_p + slip),
                       np.where(use_tp, tp_p, np.where(long, c_t, c_t + spread)))
    pnl = np.where(long, exit_px - e, e - exit_px)
    return x_off, pnl, pnl / sl


def simulate(b: Bars, idx: np.ndarray, dirs: np.ndarray, sl, tp, hold, spread: float, slip: float,
             lo: int = 0, hi: Optional[int] = None, no_overlap: bool = True, chunk: int = 6000) -> Trades:
    """Signallarni simulyatsiya qiladi. Faqat bitimi [lo, hi) oralig'ida to'liq tugaydigan signallar olinadi.
    sl/tp — narx masofasi (skalyar yoki idx bilan bir uzunlikda), hold — shamlar soni."""
    n_bars = len(b)
    hi = n_bars if hi is None else min(hi, n_bars)
    idx = np.asarray(idx, dtype=np.int64)
    if len(idx) == 0:
        return Trades.empty()
    dirs = np.broadcast_to(np.asarray(dirs), idx.shape).astype(int)
    sl = np.broadcast_to(np.asarray(sl, dtype=float), idx.shape)
    tp = np.broadcast_to(np.asarray(tp, dtype=float), idx.shape)
    hold = np.broadcast_to(np.asarray(hold, dtype=np.int64), idx.shape)
    order = np.argsort(idx, kind="stable")
    idx, dirs, sl, tp, hold = idx[order], dirs[order], sl[order], tp[order], hold[order]
    ok = (idx >= max(lo, WARMUP)) & (idx + hold + 1 < hi) & np.isfinite(sl) & (sl > 0) & np.isfinite(tp) & (tp > 0)
    idx, dirs, sl, tp, hold = idx[ok], dirs[ok], sl[ok], tp[ok], hold[ok]
    if len(idx) == 0:
        return Trades.empty()
    xs, ps, rs = [], [], []
    for a in range(0, len(idx), chunk):
        s = slice(a, a + chunk)
        x, p, r = _sim_chunk(b, idx[s], dirs[s], sl[s], tp[s], hold[s], spread, slip)
        xs.append(x), ps.append(p), rs.append(r)
    x_off, pnl, R = np.concatenate(xs), np.concatenate(ps), np.concatenate(rs)
    ent = idx + 1
    ext = ent + x_off
    if no_overlap:
        keep = np.zeros(len(idx), dtype=bool)
        last = -1
        el, xl = ent.tolist(), ext.tolist()
        for k in range(len(el)):
            if el[k] > last:
                keep[k] = True
                last = xl[k]
        ent, ext, dirs, R, pnl = ent[keep], ext[keep], dirs[keep], R[keep], pnl[keep]
    return Trades(ent, ext, dirs, R, pnl)


# ================================================================ metrikalar

def stats(t: Trades, bars_per_year: float = 252 * 23 * 4) -> Dict[str, float]:
    n = len(t)
    if n == 0:
        return {"n": 0, "win": 0.0, "exp": 0.0, "pf": 0.0, "total": 0.0, "dd": 0.0, "t": 0.0, "score": -9.0}
    R = t.R
    pos, neg = R[R > 0].sum(), -R[R < 0].sum()
    eq = np.cumsum(R)
    dd = float((np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq).max())
    sd = R.std(ddof=1) if n > 1 else 0.0
    tt = float(R.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0
    return {"n": int(n), "win": float((R > 0).mean()), "exp": float(R.mean()),
            "pf": float(pos / neg) if neg > 0 else (99.0 if pos > 0 else 0.0),
            "total": float(R.sum()), "dd": dd, "t": tt, "score": tt}


def chunk_exps(t: Trades, lo: int, hi: int, k: int = 4) -> List[float]:
    """[lo, hi) ni k bo'lakka bo'lib, har bo'lakdagi o'rtacha R (bitim yo'q bo'lsa 0)."""
    edges = np.linspace(lo, hi, k + 1)
    out = []
    for a in range(k):
        m = (t.entry_i >= edges[a]) & (t.entry_i < edges[a + 1])
        out.append(float(t.R[m].mean()) if m.any() else 0.0)
    return out


def consistent_score(t: Trades, lo: int, hi: int, min_n: int, k: int = 4) -> float:
    """Qidiruv uchun maqsad: t-statistika; bo'laklar bo'yicha barqarorlik bo'lmasa kamaytiriladi; kam bitim — jazo."""
    s = stats(t)
    if s["n"] < min_n:
        return -9.0 + s["n"] / max(1, min_n)
    sc = s["t"]
    ce = chunk_exps(t, lo, hi, k)
    neg = sum(1 for x in ce if x < 0)
    if neg >= 2:
        sc *= 0.5
    if min(ce) < -0.25:
        sc -= 0.5
    return sc


def split_ranges(n: int, ratios: Tuple[float, float, float] = (0.6, 0.2, 0.2)) -> Dict[str, Tuple[int, int]]:
    a = int(n * ratios[0])
    b = int(n * (ratios[0] + ratios[1]))
    return {"train": (0, a), "val": (a, b), "test": (b, n)}


def eff_min_t(cfg: Cfg) -> float:
    """Urinishlar soni N bo'lsa, t chegarasi Bonferroni bo'yicha oshadi: P(z>t) = 0.1587 / N (N=1 da t=1)."""
    if cfg.trials <= 1:
        return cfg.min_t
    from statistics import NormalDist
    return max(cfg.min_t, NormalDist().inv_cdf(1.0 - 0.1587 / cfg.trials))


def gate_checks(cfg: Cfg, seg: Dict[str, Dict[str, float]], test_chunks: List[float]) -> List[Dict[str, Any]]:
    """Darvozaning har bir sharti alohida: {key, label, value, need, ok} — desktop ilova infografikasi uchun."""
    te, va, tr = seg.get("test", {}), seg.get("val", {}), seg.get("train", {})
    out = [{"key": "n", "label": "Holdout bitimlari", "value": te.get("n", 0), "need": cfg.min_test_trades, "op": ">="},
           {"key": "exp", "label": "Holdout kutilma (R)", "value": te.get("exp", 0.0), "need": cfg.min_exp_r, "op": ">="},
           {"key": "pf", "label": "Holdout PF", "value": te.get("pf", 0.0), "need": cfg.min_pf, "op": ">="},
           {"key": "t", "label": "Holdout t-statistika", "value": te.get("t", 0.0), "need": eff_min_t(cfg), "op": ">="}]
    if va:
        out.append({"key": "val", "label": "Validatsiya kutilma (R)", "value": va.get("exp", 0.0), "need": 0.0, "op": ">"})
    if tr:
        out.append({"key": "train", "label": "Train kutilma (R)", "value": tr.get("exp", 0.0), "need": 0.0, "op": ">"})
    if test_chunks:
        share = sum(1 for x in test_chunks if x > 0) / len(test_chunks)
        out.append({"key": "chunks", "label": "Foydali holdout bo'laklari", "value": share, "need": cfg.min_pos_chunks, "op": ">="})
    for c in out:
        c["value"] = float(c["value"])
        c["ok"] = bool(c["value"] >= c["need"] if c["op"] == ">=" else c["value"] > c["need"])
    return out


def gate(cfg: Cfg, seg: Dict[str, Dict[str, float]], test_chunks: List[float],
         rep: Optional["Report"] = None) -> Tuple[bool, List[str]]:
    """Strategiyani jonli savdoga qo'yish uchun qabul darvozasi: tegilmagan holdout davrida foydali bo'lishi shart.
    rep berilsa, shartlar tafsiloti rep.checks ga yoziladi."""
    if rep is not None:
        rep.checks = gate_checks(cfg, seg, test_chunks)
    why: List[str] = []
    te, va, tr = seg.get("test", {}), seg.get("val", {}), seg.get("train", {})
    if te.get("n", 0) < cfg.min_test_trades:
        why.append("holdout bitimlari kam: %d < %d" % (te.get("n", 0), cfg.min_test_trades))
    if te.get("exp", 0) < cfg.min_exp_r:
        why.append("holdout kutilma %.3fR < %.3fR" % (te.get("exp", 0), cfg.min_exp_r))
    if te.get("pf", 0) < cfg.min_pf:
        why.append("holdout PF %.2f < %.2f" % (te.get("pf", 0), cfg.min_pf))
    mt = eff_min_t(cfg)
    if te.get("t", 0) < mt:
        why.append("holdout t=%.2f < %.2f%s" % (te.get("t", 0), mt, " (%d urinish uchun qattiqlashtirilgan)" % cfg.trials if cfg.trials > 1 else ""))
    if va and va.get("exp", 0) <= 0:
        why.append("validatsiya foydasiz (%.3fR)" % va.get("exp", 0))
    if tr and tr.get("exp", 0) <= 0:
        why.append("train foydasiz (%.3fR)" % tr.get("exp", 0))
    if test_chunks:
        share = sum(1 for x in test_chunks if x > 0) / len(test_chunks)
        if share < cfg.min_pos_chunks:
            why.append("holdout bo'laklarining faqat %.0f%% foydali" % (share * 100))
    return (not why), why


def parse_confirm(spec: str, cfg: Cfg) -> List[Tuple[str, float, float]]:
    out = []
    for part in [x for x in spec.split(";") if x.strip()]:
        f = [x.strip() for x in part.split("|")]
        out.append((f[0], float(f[1]) if len(f) > 1 and f[1] else cfg.spread, float(f[2]) if len(f) > 2 and f[2] else cfg.slippage))
    return out


def make_confirm(cfg: Cfg) -> Optional[Callable[[Callable[..., Trades]], Tuple[bool, List[str], Dict[str, Any]]]]:
    """Boshqa instrumentlarda (tarix fayllari) tasdiqlash: nomzod strategiya ularda ham foydali bo'lishi kerak (kamida yarmida).
    Xususiyatlar ATR ga nisbatan — instrumentga bog'liq emas; xarajat har instrument uchun alohida (spred|sirpanish)."""
    sets = parse_confirm(cfg.confirm, cfg)
    if not sets:
        return None
    cache: Dict[str, pd.DataFrame] = {}

    def run(evalfn: Callable[..., Trades]) -> Tuple[bool, List[str], Dict[str, Any]]:
        res, pos = {}, 0
        for path, sp, sj in sets:
            if path not in cache:
                cache[path] = to_tf(read_history_file(path, cfg.history_gmt), cfg.tf_min)
            s = stats(evalfn(cache[path], sp, sj))
            good = s["n"] >= 20 and s["exp"] > 0 and s["t"] > 0
            pos += good
            res[Path(path).name] = {"n": s["n"], "exp": round(s["exp"], 3), "t": round(s["t"], 2), "ok": bool(good)}
        need = (len(sets) + 1) // 2
        why = [] if pos >= need else ["tasdiqlovchi instrumentlarda foydali: %d/%d (kerak ≥ %d): %s" % (
            pos, len(sets), need, "; ".join("%s %+.3fR" % (k, v["exp"]) for k, v in res.items()))]
        return pos >= need, why, res
    return run


def fmt_stats(s: Dict[str, float]) -> str:
    return "n=%d win=%.0f%% exp=%+.3fR PF=%.2f jami=%+.1fR DD=%.1fR t=%.2f" % (
        s["n"], s["win"] * 100, s["exp"], s["pf"], s["total"], s["dd"], s["t"])


# ================================================================ dvigatel shartnomasi

@dataclass
class Signal:
    dir: int                 # +1 buy, -1 sell
    sl: float                # SL masofasi (narx birligida)
    tp: float
    hold: int                # maksimal ushlab turish (shamlarda)
    tag: str = ""


@dataclass
class Report:
    mode: str
    ok: bool = False                       # darvozadan o'tdimi
    deployed: bool = False
    summary: str = ""
    segments: Dict[str, Dict[str, float]] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    evals: int = 0
    seconds: float = 0.0
    strategy: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    checks: List[Dict[str, Any]] = field(default_factory=list)      # darvoza shartlari (gate_checks)
    curves: Dict[str, Dict[str, list]] = field(default_factory=dict)  # segment -> {t: epoch, r: R} (curves_of)

    def to_json(self) -> Dict[str, Any]:
        return {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": self.mode, "passed": self.ok,
                "deployed": self.deployed, "segments": self.segments, "reasons": self.reasons, "evals": self.evals,
                "seconds": round(self.seconds, 1), "strategy": self.strategy, "extra": self.extra}


def curves_of(res: Dict[str, Trades], index: pd.DatetimeIndex) -> Dict[str, Dict[str, list]]:
    """Segment bitimlari -> ixcham egri chiziq: kirish vaqti (epoch, s), R va yo'nalish. Faqat hisobot/ilova uchun."""
    out: Dict[str, Dict[str, list]] = {}
    for k, t in res.items():
        if t is None or not len(t):
            continue
        o = np.argsort(t.entry_i, kind="stable")
        ix = np.clip(t.entry_i[o], 0, len(index) - 1)
        out[k] = {"t": index[ix].values.astype("datetime64[s]").astype("int64").tolist(), "r": np.round(t.R[o], 3).tolist(),
                  "d": t.dirs[o].astype(int).tolist()}
    return out


def write_json(path: Path, data: Any) -> None:
    """Atomar yozish: ilova yarim yozilgan faylni o'qib qolmasligi uchun."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=float), encoding="utf-8")
    os.replace(tmp, path)


def save_report(cfg: Cfg, rep: "Report", hist: pd.DataFrame) -> Optional[Path]:
    """To'liq hisobot (egri chiziqlar, darvoza shartlari, davr chegaralari) -> state/report_<rejim>.json."""
    try:
        d = rep.to_json()
        n = len(hist)
        d.update({"symbol": cfg.symbol, "tf": cfg.tf, "checks": rep.checks, "curves": rep.curves, "bars": n,
                  "history": [str(hist.index[0]), str(hist.index[-1])] if n else [],
                  "costs": {"spread": cfg.spread, "slippage": cfg.slippage}})
        if n:
            if rep.mode == "optimizer":
                t0 = rep.curves.get("test", {}).get("t", [])
                cut = pd.Timestamp(t0[0], unit="s") if t0 else hist.index[-1]
                d["bounds"] = {"train": [str(hist.index[0]), str(cut)], "test": [str(cut), str(hist.index[-1])]}
            else:
                d["bounds"] = {k: [str(hist.index[a]), str(hist.index[min(b, n) - 1])] for k, (a, b) in split_ranges(n).items()}
        p = state_path(cfg, "report_%s.json" % rep.mode)
        write_json(p, d)
        return p
    except Exception as e:  # noqa: BLE001
        log("hisobot saqlanmadi: %s" % e)
        return None


def state_path(cfg: Cfg, name: str) -> Path:
    p = Path(cfg.state_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def append_learn_log(cfg: Cfg, rep: Report) -> None:
    try:
        with open(state_path(cfg, "learn_log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rep.to_json(), ensure_ascii=False) + "\n")
    except OSError:
        pass


# ================================================================ telegram

def telegram(text: str) -> None:
    if not env_b("TELEGRAM_ENABLED", False):
        return
    tok, chat = _env("TG_BOT_TOKEN"), _env("TG_CHAT_ID")
    if not tok or not chat:
        return
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data),
                               timeout=10).read()
    except Exception as e:  # noqa: BLE001
        log("telegram xato: %s" % e)


# ================================================================ MT5 broker

class Broker:
    """MetaTrader5 kutubxonasi ustida yupqa qatlam. `mt5` — modul (testlarda soxta modul beriladi)."""

    def __init__(self, cfg: Cfg, mt5: Any):
        self.cfg, self.mt5 = cfg, mt5
        self.server_gmt = cfg.server_gmt
        self._tf = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}[cfg.tf]

    # --- ulanish
    def connect(self) -> None:
        m = self.mt5
        kw: Dict[str, Any] = {}
        if self.cfg.terminal:
            kw = {"path": self.cfg.terminal, "portable": self.cfg.portable}
        if not m.initialize(**kw):
            raise RuntimeError("MT5 initialize xato: %s" % (m.last_error(),))
        ai = m.account_info()
        if ai is None:
            raise RuntimeError("MT5 hisob ma'lumoti yo'q")
        if self.cfg.login and int(ai.login) != self.cfg.login:
            raise RuntimeError("Terminal boshqa hisobga ulangan: %s (kutilgan SL_LOGIN=%s) — SL_TERMINAL yo'lini tekshiring" % (
                ai.login, self.cfg.login))
        if self.cfg.demo_only and int(ai.trade_mode) != int(m.ACCOUNT_TRADE_MODE_DEMO):
            raise RuntimeError("Bu robot faqat DEMO hisobda ishlaydi (SL_DEMO_ONLY=0 bilan o'chiriladi)")
        if not m.symbol_select(self.cfg.symbol, True):
            raise RuntimeError("simvol topilmadi: %s" % self.cfg.symbol)
        log("MT5 ulandi: login=%s server=%s balans=%.2f %s" % (ai.login, ai.server, ai.balance, ai.currency))
        self.detect_server_gmt()

    def detect_server_gmt(self) -> None:
        if not math.isnan(self.server_gmt):
            return
        tk = self.mt5.symbol_info_tick(self.cfg.symbol)
        if tk is None or not tk.time:
            self.server_gmt = 2.0
            return
        diff = (tk.time - time.time()) / 3600.0
        now = pd.DatetimeIndex([pd.Timestamp.now("UTC").tz_localize(None)])
        winter = round(diff) - float(us_dst(now)[0])
        self.server_gmt = float(winter)
        log("server GMT (qishki) = %+g" % self.server_gmt)

    # --- narxlar
    def bars(self, n: int) -> pd.DataFrame:
        r = self.mt5.copy_rates_from_pos(self.cfg.symbol, self._tf, 0, n)
        if r is None or len(r) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(r)
        idx = pd.DatetimeIndex(pd.to_datetime(df["time"], unit="s"))
        out = pd.DataFrame({"open": df["open"].astype(float).values, "high": df["high"].astype(float).values,
                            "low": df["low"].astype(float).values, "close": df["close"].astype(float).values,
                            "volume": df["tick_volume"].astype(float).values if "tick_volume" in df else 0.0}, index=idx)
        out.index = server_to_utc(out.index, self.server_gmt)
        return out

    def closed_bars(self, n: int) -> pd.DataFrame:
        df = self.bars(n + 1)
        return df.iloc[:-1] if len(df) else df     # oxirgi (shakllanayotgan) sham tashlanadi

    def spread_px(self) -> float:
        tk = self.mt5.symbol_info_tick(self.cfg.symbol)
        return float(tk.ask - tk.bid) if tk else 9.9

    # --- hisob / pozitsiyalar
    def balance(self) -> float:
        ai = self.mt5.account_info()
        return float(ai.balance) if ai else 0.0

    def equity(self) -> float:
        ai = self.mt5.account_info()
        return float(ai.equity) if ai else 0.0

    def positions(self) -> List[Any]:
        ps = self.mt5.positions_get(symbol=self.cfg.symbol) or []
        return [p for p in ps if int(p.magic) == self.cfg.magic]

    def lot_for_risk(self, sl_dist: float) -> Tuple[float, str]:
        """Balansning risk_pct foizi SL masofasiga to'g'ri keladigan lot. Minimal lot xavfi 2.5x dan oshsa — bitim ochilmaydi."""
        si = self.mt5.symbol_info(self.cfg.symbol)
        if si is None or sl_dist <= 0:
            return 0.0, "symbol_info yo'q"
        tick_size = si.trade_tick_size or si.point
        per_lot = sl_dist / tick_size * si.trade_tick_value          # 1 lot SL ga yetganda zarar
        if per_lot <= 0:
            return 0.0, "tick_value=0"
        risk_money = self.balance() * self.cfg.risk_pct / 100.0
        step = si.volume_step or 0.01
        lot = math.floor(risk_money / per_lot / step + 1e-9) * step
        if lot < si.volume_min:
            if si.volume_min * per_lot <= risk_money * 2.5:
                lot = si.volume_min
            else:
                return 0.0, "min lot xavfi %.2f$ > ruxsat %.2f$ (x2.5)" % (si.volume_min * per_lot, risk_money)
        lot = min(lot, si.volume_max)
        return round(lot, 8), ""

    def _filling(self, si: Any) -> int:
        fm = int(getattr(si, "filling_mode", 0))
        if fm & 1:
            return self.mt5.ORDER_FILLING_FOK
        if fm & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def open(self, sig: Signal) -> Tuple[bool, str]:
        m, c = self.mt5, self.cfg
        si, tk = m.symbol_info(c.symbol), m.symbol_info_tick(c.symbol)
        if si is None or tk is None:
            return False, "narx yo'q"
        lot, why = self.lot_for_risk(sig.sl)
        if lot <= 0:
            return False, why
        buy = sig.dir > 0
        price = float(tk.ask if buy else tk.bid)
        digits = int(si.digits)
        sl_p = price - sig.sl if buy else price + sig.sl
        tp_p = price + sig.tp if buy else price - sig.tp
        stops = float(getattr(si, "trade_stops_level", 0)) * si.point
        if stops and (sig.sl < stops or sig.tp < stops):
            return False, "SL/TP stops_level (%.2f) dan yaqin" % stops
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": c.symbol, "volume": lot,
               "type": m.ORDER_TYPE_BUY if buy else m.ORDER_TYPE_SELL, "price": price,
               "sl": round(sl_p, digits), "tp": round(tp_p, digits), "deviation": 30, "magic": c.magic,
               "comment": ("SL-%s %s" % (c.mode, sig.tag))[:30], "type_time": m.ORDER_TIME_GTC,
               "type_filling": self._filling(si)}
        r = m.order_send(req)
        if r is None or int(r.retcode) != int(m.TRADE_RETCODE_DONE):
            return False, "order_send: %s" % (getattr(r, "retcode", None) if r else m.last_error(),)
        return True, "ticket=%s lot=%s narx=%s" % (getattr(r, "order", ""), lot, price)

    def close(self, pos: Any) -> bool:
        m, c = self.mt5, self.cfg
        tk, si = m.symbol_info_tick(c.symbol), m.symbol_info(c.symbol)
        if tk is None or si is None:
            return False
        buy = int(pos.type) == int(m.POSITION_TYPE_BUY)
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": c.symbol, "volume": float(pos.volume),
               "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, "position": int(pos.ticket),
               "price": float(tk.bid if buy else tk.ask), "deviation": 30, "magic": c.magic, "comment": "SL time-exit",
               "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling(si)}
        r = m.order_send(req)
        return bool(r is not None and int(r.retcode) == int(m.TRADE_RETCODE_DONE))
