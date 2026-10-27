"""Ma'lumot manbalari: CSV (MT5 eksport va oddiy formatlar), taymfreym o'zgartirish, MT5 dan yuklash, kalendar CSV."""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}

# narx birligida odatiy spred (shamda spred bo'lmasa) va punkt — taxminiy, foydalanuvchi o'zgartira oladi
DEFAULTS = {
    "XAUUSD": (0.01, 0.30), "XAGUSD": (0.001, 0.03), "EURUSD": (0.00001, 0.00012), "GBPUSD": (0.00001, 0.00015),
    "USDJPY": (0.001, 0.015), "US500": (0.01, 0.5), "USOIL": (0.01, 0.04),
}


def guess_symbol(path: str) -> str:
    m = re.match(r"([A-Za-z0-9#._]+?)[_\-](?:M\d+|H\d+|D1|tick)", Path(path).stem)
    return (m.group(1) if m else Path(path).stem).upper()


def guess_tf(path: str) -> Optional[str]:
    m = re.search(r"(?:^|[_\-])(M1|M5|M15|M30|H1|H4|D1)(?:[_\-.]|$)", Path(path).stem.upper())
    return m.group(1) if m else None


def infer_tf(index: pd.DatetimeIndex) -> str:
    if len(index) < 3:
        return "M15"
    step = float(np.median(np.diff(index.asi8[:2000])) / 6e10)       # daqiqa
    best = min(TF_MIN, key=lambda k: abs(TF_MIN[k] - step))
    return best


def read_ohlc_csv(path: str, tz_offset_hours: float = 0.0) -> pd.DataFrame:
    """MT5 eksporti (<DATE> <TIME> <OPEN> ... <SPREAD>, tab/;/,) yoki 'time,open,high,low,close,volume' formati.
    Vaqt UTC deb olinadi; server vaqti bo'lsa tz_offset_hours bilan siljitiladi."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    sep = "\t" if "\t" in first else (";" if ";" in first else ",")
    df = pd.read_csv(io.StringIO(text), sep=sep)
    df.columns = [re.sub(r"[<>\s]", "", str(c)).lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        ts = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="coerce")
    elif "time" in df.columns:
        ts = pd.to_datetime(df["time"], errors="coerce")
    elif "datetime" in df.columns:
        ts = pd.to_datetime(df["datetime"], errors="coerce")
    elif "date" in df.columns:
        ts = pd.to_datetime(df["date"], errors="coerce")
    else:
        raise ValueError("vaqt ustuni topilmadi (date/time yoki time kerak)")
    for need in ("open", "high", "low", "close"):
        if need not in df.columns:
            raise ValueError("'%s' ustuni topilmadi" % need)
    out = pd.DataFrame({"open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"]})
    vol = df["tickvol"] if "tickvol" in df.columns else (df["volume"] if "volume" in df.columns else
                                                        (df["vol"] if "vol" in df.columns else 0.0))
    out["volume"] = vol
    if "spread" in df.columns:
        out["spread"] = pd.to_numeric(df["spread"], errors="coerce")        # punktlarda — keyin narxga o'tkaziladi
    out.index = pd.DatetimeIndex(ts)
    out = out[~out.index.isna()].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "high", "low", "close"])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    if tz_offset_hours:
        out.index = out.index - pd.Timedelta(hours=tz_offset_hours)
    return out


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = "%dmin" % TF_MIN[tf]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "spread" in df:
        agg["spread"] = "mean"
    r = df.resample(rule, label="left", closed="left").agg(agg)
    return r.dropna(subset=["open", "close"])


def import_csv(db, path: str, symbol: Optional[str] = None, tf: Optional[str] = None, target_tf: Optional[str] = None,
               tz_offset_hours: float = 0.0, progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """CSV ni bazaga yozadi. target_tf berilsa, shamlar shu davrga jamlanadi (M1 → M15)."""
    symbol = (symbol or guess_symbol(path)).upper()
    df = read_ohlc_csv(path, tz_offset_hours)
    src_tf = tf or guess_tf(path) or infer_tf(df.index)
    out_tf = target_tf or src_tf
    if TF_MIN[out_tf] < TF_MIN[src_tf]:
        raise ValueError("%s ni %s ga aylantirib bo'lmaydi (kichikroq davr)" % (src_tf, out_tf))
    pt, dsp = DEFAULTS.get(symbol, (0.01, 0.0))
    inst = db.instrument(symbol)
    if inst["default_spread"] == 0.0 and dsp:
        db.upsert_instrument(symbol, pt, dsp)
        inst = db.instrument(symbol)
    if "spread" in df:                                   # MT5 SPREAD — punktlarda
        df["spread"] = df["spread"].fillna(0) * inst["point"]
    if out_tf != src_tf:
        df = resample(df, out_tf)
    if "spread" not in df or float(df["spread"].max()) <= 0:
        df["spread"] = inst["default_spread"]
    if progress:
        progress("%s %s: %d sham yozilmoqda" % (symbol, out_tf, len(df)))
    n = db.put_bars(symbol, out_tf, df)
    return {"symbol": symbol, "tf": out_tf, "bars": n, "start": str(df.index[0]), "end": str(df.index[-1])}


def import_calendar_csv(db, path: str, tz_offset_hours: float = 0.0) -> int:
    """Kalendar CSV: ustunlar time, currency, impact (0..3 yoki low/medium/high), title (+ ixtiyoriy actual/forecast/previous).

    MQL5 skripti (mor/mql.py) yozgan format ham, qo'lda tayyorlangani ham o'qiladi. Vaqt "2022.01.03 15:30" yoki ISO bo'lishi
    mumkin; tz_offset_hours — fayldagi vaqt UTC dan qancha soatga ilgarilab ketgan (narx CSV'dagi bilan bir xil qo'ying)."""
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    if "importance" in df and "impact" not in df:
        df = df.rename(columns={"importance": "impact"})
    for need in ("time", "currency", "impact"):
        if need not in df:
            raise ValueError("Kalendar CSV da '%s' ustuni yo'q (kerak: time, currency, impact, title)" % need)
    imp_map = {"none": 0, "low": 1, "medium": 2, "med": 2, "moderate": 2, "high": 3}
    imp = pd.to_numeric(df["impact"].map(lambda x: imp_map.get(str(x).strip().lower(), x)), errors="coerce")
    t = pd.to_datetime(df["time"].astype(str).str.strip().str.replace(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", regex=True),
                       errors="coerce")
    ok = imp.notna() & t.notna() & (imp > 0) & df["currency"].notna()
    if not ok.any():
        raise ValueError("Kalendar CSV da yaroqli qator topilmadi (vaqt/ta'sir ustunlarini tekshiring)")
    t = t[ok] - pd.Timedelta(hours=float(tz_offset_hours))
    out = pd.DataFrame({"time": t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC"),
                        "currency": df.loc[ok, "currency"].astype(str).str.strip(), "impact": imp[ok].astype(int),
                        "title": df.loc[ok, "title"].astype(str) if "title" in df else ""})
    return db.put_events(out)


def mt5_download(db, symbol: str, tf: str, start: str, end: str, terminal: str = "", login: int = 0, password: str = "",
                 server: str = "", progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """MT5 terminalidan tarixni yuklaydi (faqat Windows + MetaTrader5 paketi)."""
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise RuntimeError("MetaTrader5 paketi o'rnatilmagan (faqat Windows)") from e
    kw: Dict[str, Any] = {}
    if terminal:
        kw["path"] = terminal
    if login:
        kw.update(login=int(login), password=password, server=server)
    if not mt5.initialize(**kw):
        raise RuntimeError("MT5 ga ulanib bo'lmadi: %s" % (mt5.last_error(),))
    try:
        tfc = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
               "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}[tf]
        mt5.symbol_select(symbol, True)
        a, b = pd.Timestamp(start, tz="UTC").to_pydatetime(), pd.Timestamp(end, tz="UTC").to_pydatetime()
        rates = mt5.copy_rates_range(symbol, tfc, a, b)
        if rates is None or len(rates) == 0:
            raise RuntimeError("MT5 %s %s uchun ma'lumot bermadi: %s" % (symbol, tf, mt5.last_error()))
        info = mt5.symbol_info(symbol)
        point = float(info.point) if info else 0.01
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
        out = pd.DataFrame({"open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
                            "volume": df["tick_volume"], "spread": df["spread"] * point})
        db.upsert_instrument(symbol.upper(), point, float(out["spread"].median()))
        n = db.put_bars(symbol.upper(), tf, out)
        if progress:
            progress("%s %s: %d sham" % (symbol, tf, n))
        return {"symbol": symbol.upper(), "tf": tf, "bars": n, "start": str(out.index[0]), "end": str(out.index[-1])}
    finally:
        mt5.shutdown()
