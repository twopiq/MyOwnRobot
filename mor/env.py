"""Savdo muhiti (RL): agent har sham yopilganda qaror qiladi, bitim keyingi sham ochilishida bajariladi.

Harakatlar: 0 KUTISH, 1 SOTIB OLISH (BUY), 2 SOTISH (SELL), 3 YOPISH.
Mukofot = bitim natijasi R birligida, xarajatlar (spred + sirpanish) hisobida, har qadamda taqsimlangan:
reward_t = joriy_R(t) - joriy_R(t-1), shuning uchun bitim yopilganda yig'indi aynan yakuniy natijaga teng.
Stop-loss shamning ichida tekshiriladi (avval SL — yomon holat), ochilishdagi gap hisobga olinadi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import features as F

HOLD, BUY, SELL, CLOSE = 0, 1, 2, 3
N_ACTIONS = 4
OBS_DIM = F.N_FEATURES + F.POS_FEATURES


@dataclass
class EnvCfg:
    sl_atr: float = 1.5          # stop-loss masofasi (ATR bo'yicha) = 1R
    max_hold: int = 96           # eng ko'p ushlash (sham)
    slippage_atr: float = 0.02   # sirpanish (ATR ulushi)
    elite_r: float = 1.0         # shundan yuqori natija — "namuna"
    mistake_r: float = -1.0      # shundan past natija — "xato"


@dataclass
class Series:
    symbol: str
    tf: str
    ts: np.ndarray               # sekundlarda
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    spread: np.ndarray           # narx birligida
    atr: np.ndarray
    X: np.ndarray                # [n, N_FEATURES]
    bounds: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.c)


def make_series(symbol: str, tf: str, df: pd.DataFrame, event_ts: Optional[np.ndarray] = None,
                split: Tuple[float, float, float] = (0.70, 0.15, 0.15)) -> Series:
    X, a = F.build_features(df, event_ts)
    n = len(df)
    i1, i2 = int(n * split[0]), int(n * (split[0] + split[1]))
    arr = lambda k: np.array(df[k], dtype=float)                                  # noqa: E731  (yozish mumkin bo'lgan nusxa)
    s = Series(symbol, tf, np.array(pd.DatetimeIndex(df.index).as_unit("s").asi8), arr("open"), arr("high"), arr("low"),
               arr("close"), arr("spread") if "spread" in df else np.zeros(n), a, X)
    s.bounds = {"train": (F.WARMUP, i1), "val": (i1, i2), "test": (i2, n)}
    return s


def make_obs(x: np.ndarray, side: float = 0.0, unreal: float = 0.0, held: int = 0, max_hold: int = 96,
             dist_r: float = 0.0) -> np.ndarray:
    """Kuzatuv: bozor belgilari + pozitsiya holati. O'qitish va jonli savdo AYNAN shu funksiyadan foydalanadi."""
    ob = np.zeros(OBS_DIM, dtype=np.float32)
    ob[:F.N_FEATURES] = x
    if side != 0:
        ob[F.N_FEATURES] = side
        ob[F.N_FEATURES + 1] = np.clip(unreal, -3, 3)
        ob[F.N_FEATURES + 2] = held / max_hold
        ob[F.N_FEATURES + 3] = np.clip(dist_r, -3, 3)
    return ob


def valid_actions(side: float) -> np.ndarray:
    """Pozitsiya holatiga qarab ruxsat etilgan harakatlar maskasi."""
    return np.array([True, True, True, False] if side == 0 else [True, False, False, True])


class Env:
    def __init__(self, cfg: Optional[EnvCfg] = None):
        self.cfg = cfg or EnvCfg()
        self.s: Optional[Series] = None
        self.t = 0
        self.end = 0
        self._reset_pos()

    # ------------------------------------------------------------ holat
    def _reset_pos(self) -> None:
        self.side = 0
        self.entry = 0.0
        self.risk = 1.0
        self.sl = 0.0
        self.held = 0
        self.unreal = 0.0
        self.mae = 0.0
        self.mfe = 0.0
        self.open_t = 0
        self.entry_obs: Optional[np.ndarray] = None

    def reset(self, s: Series, start: int, end: int) -> np.ndarray:
        self.s, self.t, self.end = s, int(start), int(end)
        self._reset_pos()
        return self.obs()

    def obs(self) -> np.ndarray:
        s = self.s
        if self.side == 0:
            return make_obs(s.X[self.t])
        px = s.c[self.t]
        dist = (px - self.sl) if self.side > 0 else (self.sl - (px + s.spread[self.t]))
        return make_obs(s.X[self.t], self.side, self.unreal, self.held, self.cfg.max_hold, dist / self.risk)

    @property
    def done(self) -> bool:
        return self.t >= self.end - 1

    # ------------------------------------------------------------ yordamchi
    def _mark(self, j: int) -> float:
        """Shamning yopilish narxida joriy natija (R)."""
        s = self.s
        if self.side > 0:
            return (s.c[j] - self.entry) / self.risk
        return (self.entry - (s.c[j] + s.spread[j])) / self.risk

    def _exit_r(self, price: float) -> float:
        return ((price - self.entry) if self.side > 0 else (self.entry - price)) / self.risk

    def _close(self, price: float, ts_close: int, reason: str, reward_acc: float) -> Tuple[float, Dict[str, Any]]:
        r = self._exit_r(price)
        reward = reward_acc + (r - self.unreal)
        s = self.s
        info = {"symbol": s.symbol, "tf": s.tf, "ts_open": int(s.ts[self.open_t]), "ts_close": int(ts_close),
                "side": self.side, "entry": self.entry, "exit": price, "r": r, "mae": self.mae, "mfe": self.mfe,
                "bars_held": self.held, "reason": reason, "state": self.entry_obs[:F.N_FEATURES].copy()}
        self._reset_pos()
        return reward, info

    # ------------------------------------------------------------ qadam
    def step(self, action: int, force_close: bool = False) -> Tuple[np.ndarray, float, bool, Optional[Dict[str, Any]]]:
        s, cfg = self.s, self.cfg
        j = self.t + 1
        reward, info = 0.0, None
        slip = cfg.slippage_atr * s.atr[self.t]
        want_close = self.side != 0 and (action == CLOSE or self.held >= cfg.max_hold or force_close)
        if want_close:                                               # keyingi ochilishda yopiladi
            px = s.o[j] - slip if self.side > 0 else s.o[j] + s.spread[j] + slip
            reward, info = self._close(px, s.ts[j], "agent" if action == CLOSE else "vaqt", 0.0)
        elif self.side == 0 and action in (BUY, SELL):               # keyingi ochilishda ochiladi
            self.side = 1 if action == BUY else -1
            self.risk = max(cfg.sl_atr * s.atr[self.t], 1e-9)
            self.entry = s.o[j] + s.spread[j] + slip if self.side > 0 else s.o[j] - slip
            self.sl = self.entry - self.risk if self.side > 0 else self.entry + self.risk
            self.held, self.unreal, self.mae, self.mfe, self.open_t = 0, 0.0, 0.0, 0.0, self.t
            self.entry_obs = self.obs()
        if self.side != 0:
            hit = (s.l[j] <= self.sl) if self.side > 0 else (s.h[j] + s.spread[j] >= self.sl)
            if self.side > 0:
                self.mae = min(self.mae, (s.l[j] - self.entry) / self.risk)
                self.mfe = max(self.mfe, (s.h[j] - self.entry) / self.risk)
            else:
                self.mae = min(self.mae, (self.entry - (s.h[j] + s.spread[j])) / self.risk)
                self.mfe = max(self.mfe, (self.entry - (s.l[j] + s.spread[j])) / self.risk)
            self.held += 1
            if hit:
                if self.side > 0:
                    px = min(self.sl, s.o[j]) - slip
                else:
                    px = max(self.sl, s.o[j] + s.spread[j]) + slip
                reward, info = self._close(px, s.ts[j], "stop", reward)
            else:
                m = self._mark(j)
                reward += m - self.unreal
                self.unreal = m
        self.t = j
        if self.done and self.side != 0:                              # ma'lumot tugadi — yopamiz
            px = s.c[j] if self.side > 0 else s.c[j] + s.spread[j]
            r2, info2 = self._close(px, s.ts[j], "tugadi", 0.0)
            reward += r2
            info = info2
        return self.obs(), reward, self.done, info
