"""state/ papkasidagi fayllarni o'qish va grafiklar uchun tayyorlash (Qt ga bog'liq emas)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_report(state: Path, mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """report_<rejim>.json; rejim berilmasa — eng yangisi."""
    files = [state / ("report_%s.json" % mode)] if mode else sorted(state.glob("report_*.json"), key=lambda p: p.stat().st_mtime)
    for p in reversed(files):
        if p.exists():
            d = read_json(p)
            if d:
                return d
    return None


def learn_log(state: Path, limit: int = 500) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        lines = (state / "learn_log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def live_status(state: Path, max_age: float = 30.0) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(holat, yangi_mi). Fayl max_age soniyadan eski bo'lsa — robot javob bermayapti."""
    d = read_json(state / "live_status.json")
    if not d:
        return None, False
    return d, time.time() - float(d.get("updated", 0)) <= max_age


def strategy_file(state: Path, mode: str) -> Optional[Dict[str, Any]]:
    return read_json(state / ("%s_strategy.json" % mode)) if mode != "ml" else None


_HIST_CACHE: Dict[Tuple[str, float], pd.DataFrame] = {}


def history_preview(path: str, max_points: int = 4000) -> Optional[pd.DataFrame]:
    """Tarix faylidan yopilish narxi (grafik uchun siyraklashtirilgan) + umumiy ma'lumot. Xato bo'lsa None."""
    p = Path(path)
    if not path or not p.exists():
        return None
    key = (str(p.resolve()), p.stat().st_mtime)
    if key in _HIST_CACHE:
        return _HIST_CACHE[key]
    import sl_core as sc
    try:
        df = sc.read_history_file(str(p))
    except Exception:  # noqa: BLE001
        return None
    df.attrs["bars"] = len(df)
    if len(df) > max_points:
        step = int(np.ceil(len(df) / max_points))
        small = df.iloc[::step][["close"]].copy()
        small.attrs.update(df.attrs)
        df = small
    _HIST_CACHE[key] = df
    return df


def curve_frame(rep: Dict[str, Any], seg: str) -> Optional[pd.DataFrame]:
    c = (rep.get("curves") or {}).get(seg)
    if not c or not c.get("t"):
        return None
    df = pd.DataFrame({"r": c["r"], "d": c.get("d", [0] * len(c["r"]))},
                      index=pd.to_datetime(np.asarray(c["t"], dtype="int64"), unit="s"))
    return df


def monthly_r(rep: Dict[str, Any], segs=("train", "val", "test")) -> pd.DataFrame:
    """Oylik R yig'indisi va har oy qaysi segmentga tegishli."""
    rows = []
    for s in segs:
        f = curve_frame(rep, s)
        if f is None:
            continue
        m = f["r"].groupby(f.index.to_period("M")).sum()
        for per, v in m.items():
            rows.append({"month": per.to_timestamp(), "r": float(v), "seg": s})
    if not rows:
        return pd.DataFrame(columns=["month", "r", "seg"])
    return pd.DataFrame(rows).sort_values("month").drop_duplicates("month", keep="last").reset_index(drop=True)


def fmt_r(x: float, d: int = 2) -> str:
    return ("%+." + str(d) + "fR") % x


def fmt_money(x: float, cur: str = "") -> str:
    s = "{:,.2f}".format(x).replace(",", " ")
    return s + (" " + cur if cur else "")


def ago(ts: float) -> str:
    if not ts:
        return "hech qachon"
    s = max(0, time.time() - ts)
    if s < 90:
        return "hozirgina"
    if s < 3600:
        return "%d daqiqa oldin" % (s // 60)
    if s < 86400 * 2:
        return "%d soat oldin" % (s // 3600)
    return "%d kun oldin" % (s // 86400)


def until(ts: float) -> str:
    s = ts - time.time()
    if s <= 0:
        return "hozir"
    if s < 3600:
        return "%d daqiqadan keyin" % max(1, s // 60)
    if s < 86400 * 2:
        return "%d soatdan keyin" % (s // 3600)
    return "%d kundan keyin" % (s // 86400)
