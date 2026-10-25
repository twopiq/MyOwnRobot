"""Ma'lumotlar bazasi (SQLite): shamlar, kalendar, spred, tajribalar (bitimlar xotirasi), qonuniyatlar, o'qitish yurishlari."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments(
    symbol TEXT PRIMARY KEY,
    point REAL NOT NULL DEFAULT 0.01,          -- 1 punkt narxi (MT5 SPREAD ustuni shunga ko'paytiriladi)
    default_spread REAL NOT NULL DEFAULT 0.0,  -- narx birligida; shamda spred bo'lmasa shu ishlatiladi
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bars(
    symbol TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL DEFAULT 0,
    spread REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(symbol, tf, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS events(
    ts INTEGER NOT NULL, currency TEXT NOT NULL, impact INTEGER NOT NULL DEFAULT 1, title TEXT DEFAULT '',
    PRIMARY KEY(ts, currency, title)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL NOT NULL, finished REAL,
    params TEXT NOT NULL DEFAULT '{}', metrics TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS experiences(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, split TEXT NOT NULL,
    symbol TEXT NOT NULL, tf TEXT NOT NULL, ts_open INTEGER NOT NULL, ts_close INTEGER NOT NULL,
    side INTEGER NOT NULL, entry REAL, exit REAL, r REAL NOT NULL, mae REAL, mfe REAL,
    bars_held INTEGER, reason TEXT, state BLOB
);
CREATE INDEX IF NOT EXISTS ix_exp_split ON experiences(split, symbol);
CREATE TABLE IF NOT EXISTS lessons(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created REAL NOT NULL,
    kind TEXT NOT NULL,                  -- avoid | prefer
    text TEXT NOT NULL, rule TEXT NOT NULL,
    n INTEGER, exp REAL, t REAL, oos_n INTEGER, oos_exp REAL, oos_t REAL,
    status TEXT NOT NULL DEFAULT 'candidate'   -- candidate | verified | rejected
);
CREATE TABLE IF NOT EXISTS policies(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created REAL NOT NULL,
    version INTEGER NOT NULL, path TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}', deployed INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self) -> None:
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------ instrumentlar
    def upsert_instrument(self, symbol: str, point: float = 0.01, default_spread: float = 0.0, note: str = "") -> None:
        self.con.execute(
            "INSERT INTO instruments(symbol, point, default_spread, note) VALUES(?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET point=excluded.point, default_spread=excluded.default_spread, note=excluded.note",
            (symbol, point, default_spread, note))
        self.con.commit()

    def instrument(self, symbol: str) -> Dict[str, Any]:
        r = self.con.execute("SELECT symbol, point, default_spread, note FROM instruments WHERE symbol=?", (symbol,)).fetchone()
        if r is None:
            return {"symbol": symbol, "point": 0.01, "default_spread": 0.0, "note": ""}
        return dict(zip(("symbol", "point", "default_spread", "note"), r))

    # ------------------------------------------------------------ shamlar
    def put_bars(self, symbol: str, tf: str, df: pd.DataFrame) -> int:
        """df: UTC indeks, ustunlar open/high/low/close, ixtiyoriy volume va spread (narx birligida). Qaytaradi: yozilgan qatorlar."""
        if df.empty:
            return 0
        ts = np.asarray(pd.DatetimeIndex(df.index).as_unit("s").asi8)
        vol = df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))
        spr = df["spread"].to_numpy(float) if "spread" in df else np.zeros(len(df))
        rows = list(zip([symbol] * len(df), [tf] * len(df), ts.tolist(), df["open"].to_numpy(float).tolist(),
                        df["high"].to_numpy(float).tolist(), df["low"].to_numpy(float).tolist(),
                        df["close"].to_numpy(float).tolist(), vol.tolist(), spr.tolist()))
        with self.con:
            self.con.executemany("INSERT OR REPLACE INTO bars(symbol,tf,ts,o,h,l,c,v,spread) VALUES(?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def get_bars(self, symbol: str, tf: str, start: Optional[int] = None, end: Optional[int] = None) -> pd.DataFrame:
        q = "SELECT ts,o,h,l,c,v,spread FROM bars WHERE symbol=? AND tf=?"
        args: List[Any] = [symbol, tf]
        if start is not None:
            q += " AND ts>=?"
            args.append(int(start))
        if end is not None:
            q += " AND ts<=?"
            args.append(int(end))
        df = pd.read_sql_query(q + " ORDER BY ts", self.con, params=args)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "spread"],
                                index=pd.DatetimeIndex([], tz="UTC"))
        df.index = pd.to_datetime(df.pop("ts"), unit="s", utc=True)
        df.columns = ["open", "high", "low", "close", "volume", "spread"]
        return df

    def datasets(self) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT symbol, tf, COUNT(*), MIN(ts), MAX(ts) FROM bars GROUP BY symbol, tf ORDER BY symbol, tf").fetchall()
        return [{"symbol": s, "tf": tf, "bars": n, "start": a, "end": b} for s, tf, n, a, b in rows]

    def delete_dataset(self, symbol: str, tf: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM bars WHERE symbol=? AND tf=?", (symbol, tf))

    # ------------------------------------------------------------ kalendar
    def put_events(self, df: pd.DataFrame) -> int:
        """df ustunlari: time (UTC), currency, impact (1..3), title."""
        if df.empty:
            return 0
        t = np.asarray(pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True)).as_unit("s").asi8).tolist()
        rows = list(zip(t, df["currency"].astype(str).str.upper().tolist(), df["impact"].astype(int).tolist(),
                        df.get("title", pd.Series([""] * len(df))).astype(str).tolist()))
        with self.con:
            self.con.executemany("INSERT OR REPLACE INTO events(ts,currency,impact,title) VALUES(?,?,?,?)", rows)
        return len(rows)

    def get_events(self, currencies: Optional[Sequence[str]] = None, min_impact: int = 2) -> pd.DataFrame:
        q, args = "SELECT ts, currency, impact, title FROM events WHERE impact>=?", [int(min_impact)]
        if currencies:
            q += " AND currency IN (%s)" % ",".join("?" * len(currencies))
            args += [c.upper() for c in currencies]
        df = pd.read_sql_query(q + " ORDER BY ts", self.con, params=args)
        return df

    def count(self, table: str) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])

    # ------------------------------------------------------------ yurishlar
    def start_run(self, params: Dict[str, Any]) -> int:
        cur = self.con.execute("INSERT INTO runs(started, params) VALUES(?,?)", (time.time(), json.dumps(params)))
        self.con.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, metrics: Dict[str, Any]) -> None:
        self.con.execute("UPDATE runs SET finished=?, metrics=? WHERE id=?", (time.time(), json.dumps(metrics), run_id))
        self.con.commit()

    # ------------------------------------------------------------ tajribalar xotirasi
    def add_experiences(self, run_id: int, split: str, rows: Iterable[Dict[str, Any]]) -> int:
        data = []
        for x in rows:
            st = x.get("state")
            data.append((run_id, split, x["symbol"], x["tf"], int(x["ts_open"]), int(x["ts_close"]), int(x["side"]),
                         float(x.get("entry", 0)), float(x.get("exit", 0)), float(x["r"]), float(x.get("mae", 0)),
                         float(x.get("mfe", 0)), int(x.get("bars_held", 0)), x.get("reason", ""),
                         None if st is None else np.asarray(st, dtype=np.float32).tobytes()))
        if not data:
            return 0
        with self.con:
            self.con.executemany(
                "INSERT INTO experiences(run_id,split,symbol,tf,ts_open,ts_close,side,entry,exit,r,mae,mfe,bars_held,reason,state) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
        return len(data)

    def experiences(self, split: Optional[str] = None, symbol: Optional[str] = None, outcome: Optional[str] = None,
                    limit: int = 500, order: str = "ts_close DESC") -> List[Dict[str, Any]]:
        q, args = "SELECT id,run_id,split,symbol,tf,ts_open,ts_close,side,entry,exit,r,mae,mfe,bars_held,reason FROM experiences WHERE 1=1", []
        if split:
            q += " AND split=?"
            args.append(split)
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        if outcome == "win":
            q += " AND r>0"
        elif outcome == "loss":
            q += " AND r<=0"
        if order not in ("ts_close DESC", "r ASC", "r DESC"):
            order = "ts_close DESC"
        q += " ORDER BY %s LIMIT ?" % order
        args.append(int(limit))
        cols = ("id", "run_id", "split", "symbol", "tf", "ts_open", "ts_close", "side", "entry", "exit", "r", "mae", "mfe",
                "bars_held", "reason")
        return [dict(zip(cols, r)) for r in self.con.execute(q, args).fetchall()]

    def experience_arrays(self, split: str) -> Dict[str, np.ndarray]:
        """Qonuniyat qidirish uchun: R, yo'nalish, vaqt, belgilar (state) — to'liq massivlar."""
        rows = self.con.execute("SELECT r, side, ts_open, symbol, state FROM experiences WHERE split=? AND state IS NOT NULL",
                                (split,)).fetchall()
        if not rows:
            return {"r": np.zeros(0), "side": np.zeros(0, int), "ts": np.zeros(0, int), "symbol": np.zeros(0, object),
                    "X": np.zeros((0, 0), np.float32)}
        X = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
        return {"r": np.array([r[0] for r in rows]), "side": np.array([r[1] for r in rows]),
                "ts": np.array([r[2] for r in rows]), "symbol": np.array([r[3] for r in rows], dtype=object), "X": X}

    def experience_stats(self) -> Dict[str, Any]:
        n, mean, wins = self.con.execute("SELECT COUNT(*), AVG(r), SUM(r>0) FROM experiences").fetchone()
        syms = self.con.execute("SELECT COUNT(DISTINCT symbol) FROM experiences").fetchone()[0]
        return {"n": int(n or 0), "mean_r": float(mean or 0.0), "wins": int(wins or 0), "symbols": int(syms or 0)}

    def clear_experiences(self) -> None:
        with self.con:
            self.con.execute("DELETE FROM experiences")

    # ------------------------------------------------------------ qonuniyatlar
    def replace_lessons(self, run_id: int, lessons: List[Dict[str, Any]]) -> None:
        with self.con:
            self.con.execute("DELETE FROM lessons")
            for x in lessons:
                self.con.execute(
                    "INSERT INTO lessons(run_id,created,kind,text,rule,n,exp,t,oos_n,oos_exp,oos_t,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, time.time(), x["kind"], x["text"], json.dumps(x["rule"]), x["n"], x["exp"], x["t"],
                     x.get("oos_n", 0), x.get("oos_exp", 0.0), x.get("oos_t", 0.0), x.get("status", "candidate")))

    def lessons(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT id,kind,text,rule,n,exp,t,oos_n,oos_exp,oos_t,status FROM lessons"
        args: List[Any] = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        out = []
        for r in self.con.execute(q + " ORDER BY status DESC, ABS(oos_t) DESC", args).fetchall():
            d = dict(zip(("id", "kind", "text", "rule", "n", "exp", "t", "oos_n", "oos_exp", "oos_t", "status"), r))
            d["rule"] = json.loads(d["rule"])
            out.append(d)
        return out

    # ------------------------------------------------------------ siyosatlar
    def add_policy(self, run_id: int, version: int, path: str, metrics: Dict[str, Any], deployed: bool) -> int:
        cur = self.con.execute("INSERT INTO policies(run_id,created,version,path,metrics,deployed) VALUES(?,?,?,?,?,?)",
                               (run_id, time.time(), version, path, json.dumps(metrics), int(deployed)))
        self.con.commit()
        return int(cur.lastrowid)

    def latest_policy(self, deployed_only: bool = False) -> Optional[Dict[str, Any]]:
        q = "SELECT id,run_id,created,version,path,metrics,deployed FROM policies"
        if deployed_only:
            q += " WHERE deployed=1"
        r = self.con.execute(q + " ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(zip(("id", "run_id", "created", "version", "path", "metrics", "deployed"), r))
        d["metrics"] = json.loads(d["metrics"])
        return d
