"""O'qitish: agent ko'p instrumentli tarixda tajriba qiladi (bitim ochadi/yopadi), tajribalar bazaga yoziladi,
yutuq va xatolardan qayta o'rganadi, so'ng topilgan qonuniyatlar tekshiriladi.

Halollik qoidasi: har bir instrumentning tarixi vaqt bo'yicha 70% o'qitish / 15% tasdiqlash (val) / 15% test (test) ga bo'linadi.
Agent faqat o'qitish qismida o'rganadi; eng yaxshi nuqta val bo'yicha tanlanadi; test faqat YAKUNIY hisobot uchun ishlatiladi.
"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from . import features as F
from .agent import ELITE, MISTAKE, Agent, Replay
from .db import Database
from .env import Env, EnvCfg, OBS_DIM, Series, make_series
from .lessons import Guard, MineCfg, mine
from .paths import models_dir


@dataclass
class TrainCfg:
    tf: str = "M15"
    symbols: List[str] = field(default_factory=list)       # bo'sh = bazadagi barcha shu taymfreym datasetlari
    epochs: int = 200
    envs: int = 16
    episode_len: int = 1500
    eval_every: int = 10
    hidden: Tuple[int, ...] = (128, 128)
    lr: float = 3e-4
    gamma: float = 0.99
    batch: int = 64
    replay: int = 200_000
    learn_every: int = 4
    warmup: int = 2000
    eps_start: float = 1.0
    eps_end: float = 0.05
    eps_decay: float = 0.6
    hold_bias: float = 0.9
    share_elite: float = 0.1
    share_mistake: float = 0.1
    sl_atr: float = 1.5
    max_hold: int = 96
    seed: int = 0
    resume: bool = True
    min_trades: int = 100                                   # tanlash/darvoza uchun eng kam bitim
    gate_exp: float = 0.05
    gate_t: float = 2.0
    max_seconds: float = 0.0                                # 0 = cheklovsiz
    use_events: bool = True


def trade_stats(R: np.ndarray) -> Dict[str, float]:
    n = len(R)
    if n == 0:
        return {"n": 0, "exp": 0.0, "pf": 0.0, "t": 0.0, "win": 0.0, "sum": 0.0, "dd": 0.0}
    gp, gl = float(R[R > 0].sum()), float(-R[R < 0].sum())
    sd = float(R.std(ddof=1)) if n > 1 else 0.0
    eq = np.cumsum(R)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {"n": n, "exp": float(R.mean()), "pf": gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0),
            "t": float(R.mean() / (sd / np.sqrt(n))) if sd > 1e-12 else 0.0, "win": float((R > 0).mean()),
            "sum": float(R.sum()), "dd": dd}


def load_series(db: Database, cfg: TrainCfg) -> List[Series]:
    syms = cfg.symbols or [d["symbol"] for d in db.datasets() if d["tf"] == cfg.tf]
    out = []
    for sym in syms:
        df = db.get_bars(sym, cfg.tf)
        if len(df) < 3000:
            continue
        ev = None
        if cfg.use_events:
            e = db.get_events(min_impact=3)
            if len(e):
                cur = _currencies_of(sym)
                e = e[e["currency"].isin(cur)] if cur else e
                ev = e["ts"].to_numpy(np.int64) if len(e) else None
        out.append(make_series(sym, cfg.tf, df, ev))
    return out


def _currencies_of(sym: str) -> List[str]:
    s = sym.upper()
    if s.startswith(("XAU", "XAG")):
        return ["USD"]
    if s in ("US500", "USOIL", "US30", "USTEC"):
        return ["USD"]
    if len(s) >= 6 and s[:6].isalpha():
        return [s[:3], s[3:6]]
    return []


class Trainer:
    def __init__(self, db: Database, cfg: TrainCfg, on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
                 stop: Optional[Callable[[], bool]] = None):
        self.db, self.cfg = db, cfg
        self.emit = on_event or (lambda e: None)
        self.stop = stop or (lambda: False)
        self.rng = np.random.default_rng(cfg.seed)
        self.env_cfg = EnvCfg(sl_atr=cfg.sl_atr, max_hold=cfg.max_hold)

    def log(self, msg: str) -> None:
        self.emit({"type": "log", "msg": msg})

    # ------------------------------------------------------------ yurish
    def rollout(self, agent: Agent, series: List[Series], rb: Replay, eps: float, learn: bool) -> Tuple[List[Dict], int]:
        cfg = self.cfg
        K = cfg.envs
        envs, obs = [], []
        for _ in range(K):
            s = series[int(self.rng.integers(len(series)))]
            lo, hi = s.bounds["train"]
            L = min(cfg.episode_len, hi - lo - 2)
            start = int(self.rng.integers(lo, hi - L))
            e = Env(self.env_cfg)
            obs.append(e.reset(s, start, start + L))
            envs.append(e)
        L = min(e.end - e.t for e in envs)
        obs = np.stack(obs)
        trans: List[List[int]] = [[] for _ in range(K)]
        trades: List[Dict] = []
        steps = 0
        for step in range(L - 1):
            mask = Agent.mask_from_obs(obs, F.N_FEATURES)
            act = agent.act(obs, mask, eps, cfg.hold_bias)
            nxt = np.empty_like(obs)
            for k, e in enumerate(envs):
                o2, r, d, info = e.step(int(act[k]))
                idx = rb.add(obs[k], act[k], r, o2, float(d))
                if info is not None:
                    trans[k].append(idx)
                    rr = info["r"]
                    if rr >= self.env_cfg.elite_r:
                        rb.mark(trans[k], ELITE)
                    elif rr <= self.env_cfg.mistake_r:
                        rb.mark(trans[k], MISTAKE)
                    trades.append(info)
                    trans[k] = []
                elif e.side == 0:
                    trans[k] = []
                else:
                    trans[k].append(idx)
                nxt[k] = o2
            obs = nxt
            steps += K
            if learn and rb.n >= cfg.warmup and step % cfg.learn_every == 0:
                agent.learn(rb, cfg.batch, F.N_FEATURES, cfg.share_elite, cfg.share_mistake)
        return trades, steps

    def evaluate(self, agent: Agent, series: List[Series], split: str, guard: Optional[Guard] = None,
                 max_bars: int = 0) -> List[Dict]:
        """Ochko'z (eps=0) yurish: har instrument segmenti bo'ylab ketma-ket."""
        envs = []
        for s in series:
            lo, hi = s.bounds[split]
            if max_bars and hi - lo > max_bars:
                lo = hi - max_bars
            e = Env(self.env_cfg)
            e.reset(s, lo, hi)
            envs.append(e)
        trades: List[Dict] = []
        while True:
            act_ix = [i for i, e in enumerate(envs) if not e.done]
            if not act_ix:
                break
            obs = np.stack([envs[i].obs() for i in act_ix])
            mask = Agent.mask_from_obs(obs, F.N_FEATURES)
            a = agent.q_values(obs)
            a = np.where(mask, a, -1e9).argmax(1)
            for j, i in enumerate(act_ix):
                act = int(a[j])
                if guard is not None and act in (1, 2) and guard.veto(obs[j][:F.N_FEATURES], 1 if act == 1 else -1):
                    act = 0
                _, _, _, info = envs[i].step(act)
                if info is not None:
                    trades.append(info)
        return trades

    # ------------------------------------------------------------ asosiy sikl
    def run(self) -> Dict[str, Any]:
        cfg, db = self.cfg, self.db
        series = load_series(db, cfg)
        if not series:
            raise RuntimeError("O'qitish uchun ma'lumot yo'q: %s taymfreymda kamida 3000 shamli dataset kerak" % cfg.tf)
        self.log("Datasetlar: %s" % ", ".join("%s (%d)" % (s.symbol, len(s)) for s in series))
        agent = Agent(cfg.hidden, cfg.lr, cfg.gamma, cfg.seed)
        resumed = False
        if cfg.resume:
            last = db.latest_policy()
            if last:
                try:
                    ag2 = Agent.load(last["path"])
                    if ag2.sizes == agent.sizes:
                        agent, resumed = ag2, True
                        agent.lr, agent.gamma = cfg.lr, cfg.gamma
                        self.log("Oldingi siyosat (v%d) dan davom etilmoqda" % last["version"])
                except Exception as e:  # noqa: BLE001
                    self.log("Oldingi siyosat yuklanmadi: %s" % e)
        rb = Replay(cfg.replay)
        run_id = db.start_run({k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()})
        best = {"score": -1e9, "state": None, "epoch": 0, "val": None}
        history: List[Dict[str, Any]] = []
        t0 = time.time()
        total_steps = 0
        eps0 = 0.3 if resumed else cfg.eps_start
        for ep in range(1, cfg.epochs + 1):
            if self.stop() or (cfg.max_seconds and time.time() - t0 > cfg.max_seconds):
                self.log("To'xtatildi (epoxa %d)" % (ep - 1))
                break
            frac = min(1.0, ep / max(1.0, cfg.eps_decay * cfg.epochs))
            eps = max(cfg.eps_end, eps0 - (eps0 - cfg.eps_end) * frac)
            te = time.time()
            trades, steps = self.rollout(agent, series, rb, eps, True)
            total_steps += steps
            db.add_experiences(run_id, "train", trades)
            R = np.array([t["r"] for t in trades]) if trades else np.zeros(0)
            ev = {"type": "epoch", "epoch": ep, "epochs": cfg.epochs, "eps": eps, "trades": len(trades),
                  "mean_r": float(R.mean()) if len(R) else 0.0, "loss": agent.last_loss, "memory": rb.counts(),
                  "sps": steps / max(1e-9, time.time() - te), "steps": total_steps}
            if ep % cfg.eval_every == 0 or ep == cfg.epochs:
                val = trade_stats(np.array([t["r"] for t in self.evaluate(agent, series, "val")]))
                trn = trade_stats(np.array([t["r"] for t in self.evaluate(agent, series, "train", max_bars=6000)]))
                ev.update(val=val, train_eval=trn)
                score = val["exp"] * np.sqrt(val["n"]) if val["n"] >= cfg.min_trades else -1e3 + val["n"]
                if score > best["score"]:
                    best.update(score=score, state=copy.deepcopy(agent.q.state()), epoch=ep, val=val)
                    ev["best"] = True
            history.append({k: v for k, v in ev.items() if k != "type"})
            self.emit(ev)
        # ---- yakuniy: eng yaxshi nuqta, qonuniyatlar, test
        if best["state"] is not None:
            agent.q.load_state(best["state"])
        agent.target.copy_from(agent.q)
        result = self.finalize(agent, series, run_id, best, history, time.time() - t0, total_steps)
        return result

    def finalize(self, agent: Agent, series: List[Series], run_id: int, best: Dict[str, Any], history: List[Dict],
                 seconds: float, steps: int) -> Dict[str, Any]:
        cfg, db = self.cfg, self.db
        self.log("Yakuniy tekshiruv: val va test (agent bu davrlarni o'rganmagan)")
        val_tr = self.evaluate(agent, series, "val")
        test_tr = self.evaluate(agent, series, "test")
        db.add_experiences(run_id, "val", val_tr)
        db.add_experiences(run_id, "test", test_tr)
        lessons = mine(db.experience_arrays("train"), db.experience_arrays("val"), MineCfg())
        db.replace_lessons(run_id, lessons)
        guard = Guard(lessons)
        test_g = self.evaluate(agent, series, "test", guard) if len(guard) else test_tr
        val_g = self.evaluate(agent, series, "val", guard) if len(guard) else val_tr
        m = {
            "val": trade_stats(np.array([t["r"] for t in val_tr])), "test": trade_stats(np.array([t["r"] for t in test_tr])),
            "val_guard": trade_stats(np.array([t["r"] for t in val_g])),
            "test_guard": trade_stats(np.array([t["r"] for t in test_g])),
            "guard_rules": len(guard), "lessons_verified": sum(1 for x in lessons if x["status"] == "verified"),
            "best_epoch": best["epoch"], "seconds": seconds, "steps": steps, "symbols": [s.symbol for s in series],
            "per_symbol_test": {s.symbol: trade_stats(np.array([t["r"] for t in test_g if t["symbol"] == s.symbol]))
                                for s in series},
            "history": history[-400:],
        }
        use = m["test_guard"] if len(guard) else m["test"]
        vuse = m["val_guard"] if len(guard) else m["val"]
        ok = bool(use["n"] >= cfg.min_trades and use["exp"] >= cfg.gate_exp and use["t"] >= cfg.gate_t and vuse["exp"] > 0)
        m["gate_ok"] = ok
        m["gate"] = {"n": use["n"], "exp": use["exp"], "t": use["t"], "need_n": cfg.min_trades, "need_exp": cfg.gate_exp,
                     "need_t": cfg.gate_t, "val_exp": vuse["exp"]}
        prev = db.latest_policy()
        ver = (prev["version"] + 1) if prev else 1
        path = str(models_dir() / ("policy_v%d.npz" % ver))
        agent.save(path, {"tf": cfg.tf, "symbols": m["symbols"], "env": asdict(self.env_cfg), "guard": [x for x in lessons
                          if x["status"] == "verified" and x["kind"] == "avoid"], "gate_ok": ok,
                          "hidden": list(cfg.hidden)})
        db.add_policy(run_id, ver, path, {k: v for k, v in m.items() if k not in ("history",)}, ok)
        db.finish_run(run_id, {k: v for k, v in m.items() if k != "history"})
        m["policy_version"], m["policy_path"] = ver, path
        self.emit({"type": "done", "metrics": m})
        return m
