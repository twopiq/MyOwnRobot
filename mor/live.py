"""Jonli savdo: MT5 (faqat DEMO hisob), tayyor siyosat bo'yicha har yopilgan shamda qaror, xavf nazorati."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from . import features as F
from .agent import Agent
from .env import BUY, CLOSE, HOLD, SELL, EnvCfg, make_obs
from .lessons import Guard

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


@dataclass
class LiveCfg:
    symbol: str = "XAUUSD"
    tf: str = "M15"
    risk_pct: float = 0.25                 # bitim boshiga hisobning foizi
    max_daily_loss_pct: float = 2.0        # kunlik zarar chegarasi
    kill_r: float = -6.0                   # oxirgi 20 bitim yig'indisi shundan past bo'lsa — to'xtaydi
    demo_only: bool = True
    magic: int = 20260
    terminal: str = ""
    portable: bool = False
    login: int = 0
    password: str = ""
    server: str = ""
    poll_sec: float = 5.0
    bars: int = 600
    use_events: bool = True


# ============================================================ MT5 qatlami
class Broker:
    """MetaTrader5 ustidan yupqa qatlam. Testlarda uning o'rniga soxta broker beriladi."""

    def __init__(self, cfg: LiveCfg):
        self.cfg = cfg
        self.mt5: Any = None
        self.offset_h = 0.0

    def connect(self) -> Dict[str, Any]:
        try:
            import MetaTrader5 as mt5
        except ImportError as e:
            raise RuntimeError("MetaTrader5 paketi yo'q (faqat Windows)") from e
        self.mt5 = mt5
        c = self.cfg
        kw: Dict[str, Any] = {}
        if c.terminal:
            kw["path"] = c.terminal
        if c.portable:
            kw["portable"] = True
        if c.login:
            kw.update(login=int(c.login), password=c.password, server=c.server)
        if not mt5.initialize(**kw):
            raise RuntimeError("MT5 ga ulanib bo'lmadi: %s" % (mt5.last_error(),))
        ai = mt5.account_info()
        if ai is None:
            raise RuntimeError("Hisob ma'lumoti olinmadi: %s" % (mt5.last_error(),))
        if c.login and int(ai.login) != int(c.login):
            raise RuntimeError("Terminal boshqa hisobga ulangan: %s (kutilgan %s). Parolni kiriting." % (ai.login, c.login))
        if c.demo_only and ai.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            mt5.shutdown()
            raise RuntimeError("Bu DEMO hisob emas — xavfsizlik uchun savdo o'chirildi")
        if not mt5.symbol_select(c.symbol, True):
            raise RuntimeError("Simvol topilmadi: %s" % c.symbol)
        self._detect_offset()
        return {"login": int(ai.login), "server": ai.server, "balance": float(ai.balance), "equity": float(ai.equity),
                "currency": ai.currency}

    def _detect_offset(self) -> None:
        t = self.mt5.symbol_info_tick(self.cfg.symbol)
        if t and t.time:
            diff = (t.time - time.time()) / 3600.0
            self.offset_h = round(diff * 2) / 2.0

    def shutdown(self) -> None:
        if self.mt5:
            self.mt5.shutdown()

    def bars(self, n: int) -> pd.DataFrame:
        mt5 = self.mt5
        tfc = getattr(mt5, "TIMEFRAME_" + self.cfg.tf)
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, tfc, 0, n)
        if rates is None or len(rates) == 0:
            raise RuntimeError("Shamlar olinmadi: %s" % (mt5.last_error(),))
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df.pop("time") - int(self.offset_h * 3600), unit="s", utc=True)
        info = mt5.symbol_info(self.cfg.symbol)
        pt = float(info.point) if info else 0.01
        return pd.DataFrame({"open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
                             "volume": df["tick_volume"], "spread": df["spread"] * pt})

    def account(self) -> Dict[str, float]:
        ai = self.mt5.account_info()
        return {"balance": float(ai.balance), "equity": float(ai.equity)}

    def position(self) -> Optional[Dict[str, Any]]:
        ps = self.mt5.positions_get(symbol=self.cfg.symbol)
        for p in ps or ():
            if p.magic == self.cfg.magic:
                return {"ticket": p.ticket, "side": 1 if p.type == self.mt5.POSITION_TYPE_BUY else -1, "entry": p.price_open,
                        "sl": p.sl, "volume": p.volume, "time": p.time - int(self.offset_h * 3600), "profit": p.profit}
        return None

    def deal_profit(self, ticket: int) -> float:
        deals = self.mt5.history_deals_get(position=ticket)
        return float(sum(d.profit + d.commission + d.swap for d in (deals or ())))

    def tick(self) -> Dict[str, float]:
        t = self.mt5.symbol_info_tick(self.cfg.symbol)
        return {"bid": float(t.bid), "ask": float(t.ask)}

    def lots_for(self, risk_money: float, sl_dist: float) -> float:
        mt5 = self.mt5
        info = mt5.symbol_info(self.cfg.symbol)
        tick_val, tick_size = info.trade_tick_value, info.trade_tick_size
        loss_per_lot = sl_dist / tick_size * tick_val
        if loss_per_lot <= 0:
            return 0.0
        lots = risk_money / loss_per_lot
        step = info.volume_step
        lots = np.floor(lots / step) * step
        if lots < info.volume_min:
            return 0.0                                  # eng kichik lot ham ruxsat etilgan xavfdan oshadi
        return float(min(lots, info.volume_max))

    def _fill(self) -> int:
        mt5 = self.mt5
        fm = self.mt5.symbol_info(self.cfg.symbol).filling_mode
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def open(self, side: int, lots: float, sl: float) -> Dict[str, Any]:
        mt5 = self.mt5
        info = mt5.symbol_info(self.cfg.symbol)
        t = self.tick()
        price = t["ask"] if side > 0 else t["bid"]
        min_dist = info.trade_stops_level * info.point
        if abs(price - sl) < min_dist:
            raise RuntimeError("SL brokerning minimal masofasidan yaqin (%.5f < %.5f)" % (abs(price - sl), min_dist))
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.cfg.symbol, "volume": lots,
               "type": mt5.ORDER_TYPE_BUY if side > 0 else mt5.ORDER_TYPE_SELL, "price": price, "sl": sl, "deviation": 20,
               "magic": self.cfg.magic, "comment": "MyOwnRobot", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": self._fill()}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError("Buyurtma rad etildi: %s" % (r,))
        return {"ticket": r.order, "price": r.price}

    def close(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        mt5 = self.mt5
        t = self.tick()
        side = pos["side"]
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.cfg.symbol, "volume": pos["volume"],
               "type": mt5.ORDER_TYPE_SELL if side > 0 else mt5.ORDER_TYPE_BUY, "position": pos["ticket"],
               "price": t["bid"] if side > 0 else t["ask"], "deviation": 20, "magic": self.cfg.magic,
               "comment": "MyOwnRobot", "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._fill()}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError("Yopish rad etildi: %s" % (r,))
        return {"price": r.price}


# ============================================================ jonli sikl
class LiveRunner:
    def __init__(self, cfg: LiveCfg, policy_path: str, broker: Any, event_ts: Optional[np.ndarray] = None,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None, stop: Optional[Callable[[], bool]] = None):
        self.cfg, self.broker = cfg, broker
        self.agent = Agent.load(policy_path)
        meta = Agent.load_meta(policy_path)
        env = meta.get("env", {})
        self.env_cfg = EnvCfg(sl_atr=env.get("sl_atr", 1.5), max_hold=env.get("max_hold", 96))
        self.guard = Guard(meta.get("guard", []))
        self.event_ts = event_ts
        self.emit = on_event or (lambda e: None)
        self.stop = stop or (lambda: False)
        self.last_bar_ts: Optional[int] = None
        self.recent_r: List[float] = []
        self.day_start_equity: Optional[float] = None
        self.day = ""
        self.paused_reason = ""
        self._tracked: Optional[int] = None          # ochiq pozitsiya chiptasi
        self._risk_money: float = 0.0

    def log(self, msg: str) -> None:
        self.emit({"type": "log", "msg": msg})

    # ------------------------------------------------------------ xavf
    def risk_blocked(self) -> str:
        acc = self.broker.account()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self.day:
            self.day, self.day_start_equity = today, acc["equity"]
        if self.day_start_equity and acc["equity"] < self.day_start_equity * (1 - self.cfg.max_daily_loss_pct / 100.0):
            return "kunlik zarar chegarasi (%.1f%%)" % self.cfg.max_daily_loss_pct
        if len(self.recent_r) >= 20 and sum(self.recent_r[-20:]) <= self.cfg.kill_r:
            return "oxirgi 20 bitim %.1fR — avtomatik to'xtatish" % sum(self.recent_r[-20:])
        return ""

    # ------------------------------------------------------------ bitta qaror
    def decide(self, df: pd.DataFrame) -> Dict[str, Any]:
        """df: oxirgi YOPILGAN shamgacha. Qaytaradi: {action, obs, atr, q}."""
        X, a = F.build_features(df, self.event_ts)
        pos = self.broker.position()
        last = df.iloc[-1]
        if pos is None:
            obs = make_obs(X[-1])
        else:
            risk = abs(pos["entry"] - pos["sl"]) if pos["sl"] else self.env_cfg.sl_atr * a[-1]
            px = float(last["close"])
            if pos["side"] > 0:
                unreal, dist = (px - pos["entry"]) / risk, (px - pos["sl"]) / risk
            else:
                unreal, dist = (pos["entry"] - (px + float(last["spread"]))) / risk, (pos["sl"] - px) / risk
            held = int((df.index[-1].value // 10**9 - pos["time"]) // TF_SECONDS[self.cfg.tf])
            obs = make_obs(X[-1], pos["side"], unreal, held, self.env_cfg.max_hold, dist)
        mask = Agent.mask_from_obs(obs[None, :], F.N_FEATURES)
        q = self.agent.q_values(obs)
        act = int(np.where(mask, q, -1e9).argmax())
        if pos is not None and (int(obs[F.N_FEATURES + 2] * self.env_cfg.max_hold) >= self.env_cfg.max_hold):
            act = CLOSE
        if act in (BUY, SELL) and self.guard.veto(obs[:F.N_FEATURES], 1 if act == BUY else -1):
            act = HOLD
        return {"action": act, "atr": float(a[-1]), "q": [round(float(x), 4) for x in q[0]], "pos": pos}

    def step_once(self) -> Optional[Dict[str, Any]]:
        """Yangi yopilgan sham bo'lsa qaror qiladi va bajaradi. Qaytaradi: hodisa yoki None."""
        df = self.broker.bars(self.cfg.bars)
        df = df.iloc[:-1]                                             # oxirgisi hali shakllanmoqda
        ts = int(df.index[-1].value // 10**9)
        if ts == self.last_bar_ts:
            return None
        self.last_bar_ts = ts
        d = self.decide(df)
        act, pos = d["action"], d["pos"]
        if self._tracked is not None and pos is None and self._risk_money > 0:       # pozitsiya yopilgan — natijani yozamiz
            r = self.broker.deal_profit(self._tracked) / self._risk_money
            self.recent_r.append(r)
            self.emit({"type": "trade_closed", "ticket": self._tracked, "r": round(r, 3)})
            self._tracked = None
        blocked = self.risk_blocked()
        ev: Dict[str, Any] = {"type": "decision", "ts": ts, "action": ["KUTISH", "BUY", "SELL", "YOPISH"][act], "q": d["q"],
                              "blocked": blocked}
        if pos is None and act in (BUY, SELL):
            if blocked:
                ev["note"] = "savdo to'xtatilgan: " + blocked
                self.paused_reason = blocked
            else:
                side = 1 if act == BUY else -1
                risk_dist = self.env_cfg.sl_atr * d["atr"]
                eq = self.broker.account()["equity"]
                lots = self.broker.lots_for(eq * self.cfg.risk_pct / 100.0, risk_dist)
                if lots <= 0:
                    ev["note"] = "lot hisoblanmadi (hisob kichik yoki SL keng)"
                else:
                    t = self.broker.tick()
                    entry = t["ask"] if side > 0 else t["bid"]
                    sl = entry - risk_dist if side > 0 else entry + risk_dist
                    res = self.broker.open(side, lots, sl)
                    self._tracked, self._risk_money = res.get("ticket"), eq * self.cfg.risk_pct / 100.0
                    ev.update(opened=res, lots=lots, sl=sl)
        elif pos is not None and act == CLOSE:
            ev["closed"] = self.broker.close(pos)
        self.emit(ev)
        return ev

    def run(self) -> None:
        self.log("Jonli savdo boshlandi: %s %s" % (self.cfg.symbol, self.cfg.tf))
        while not self.stop():
            try:
                self.step_once()
            except Exception as e:  # noqa: BLE001
                self.emit({"type": "error", "msg": str(e)})
            time.sleep(self.cfg.poll_sec)
        self.log("Jonli savdo to'xtatildi")
