"""Self-learning robot (MT5, Python) — o'zi o'rganadigan va o'z strategiyasini shakllantiradigan robot.

Rejim env o'zgaruvchisi bilan tanlanadi:   SL_MODE = genetic | optimizer | ml
(Jonli → Python robotlar → «Muhit o'zgaruvchilari» maydoniga yozing, masalan  SL_MODE=optimizer)

Jonli ish:  tarix (fayl + MT5 dagi so'nggi shamlar) -> o'rganish (dvigatel) -> tegilmagan davrda tekshiruv ->
            o'tsa — shu strategiya bilan DEMO hisobda savdo; har SL_RELEARN_HOURS soatda qayta o'rganadi.
Oflayn tadqiqot (savdosiz, MT5 kerak emas):
            python selflearn_robot.py --learn --mode genetic --history XAUUSD_M15.csv

Muhim env: SL_MODE, SL_HISTORY, SL_RISK_PCT, SL_RELEARN_HOURS, SL_BUDGET_SEC, SL_REQUIRE_PASS, SL_SPREAD, SL_SLIPPAGE,
SL_TF (M15), SL_MAGIC, SL_MAX_DAILY_LOSS_PCT, SL_DEMO_ONLY. Batafsil: selflearn/README.md
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sl_core as sc  # noqa: E402


def load_engine(cfg: sc.Cfg) -> Any:
    """Faqat tanlangan rejimning moduli import qilinadi — boshqa ikkitasi umuman yuklanmaydi."""
    mod = importlib.import_module({"genetic": "sl_genetic", "optimizer": "sl_optimizer", "ml": "sl_ml"}[cfg.mode])
    return mod.Engine(cfg)


# ================================================================ tarix

def build_history(cfg: sc.Cfg, br: Optional[sc.Broker] = None) -> pd.DataFrame:
    base: Optional[pd.DataFrame] = None
    if cfg.history:
        p = Path(cfg.history)
        if not p.exists():
            sc.log("DIQQAT: tarix fayli topilmadi: %s" % cfg.history)
        else:
            base = sc.limit_years(sc.to_tf(sc.read_history_file(str(p), cfg.history_gmt), cfg.tf_min), cfg.history_years)
            sc.log("tarix fayli: %d sham, %s .. %s" % (len(base), base.index[0], base.index[-1]))
    recent: Optional[pd.DataFrame] = None
    if br is not None:
        try:
            recent = br.closed_bars(60000)
            if len(recent):
                sc.log("MT5 tarixi: %d sham, %s .. %s" % (len(recent), recent.index[0], recent.index[-1]))
        except Exception as e:  # noqa: BLE001
            sc.log("MT5 tarixini olib bo'lmadi: %s" % e)
    parts = [x for x in (base, recent) if x is not None and len(x)]
    if not parts:
        raise RuntimeError("tarix yo'q: SL_HISTORY faylini bering yoki MT5 ulanishini tekshiring")
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return sc.limit_years(df, cfg.history_years)


def learn_repeat(cfg: sc.Cfg, hist: pd.DataFrame, base: Any = None):
    """Yangi seed bilan cfg.repeat marta o'rganadi; ko'p urinish — darvoza Bonferroni bo'yicha qattiqlashadi.
    Birinchi o'tgan urinishda to'xtaydi. Qaytaradi: (dvigatel, hisobot)."""
    n = max(1, cfg.repeat)
    last: Optional[tuple] = None
    for k in range(n):
        c = dataclasses.replace(cfg, seed=cfg.seed + k, trials=max(cfg.trials, n))
        eng = load_engine(c)
        eng.load()
        cb = progress_printer(k, n)
        rep = eng.learn(hist, progress=cb) if cb else eng.learn(hist)
        rep.extra["attempt"] = "%d/%d" % (k + 1, n)
        if n > 1:
            sc.log("urinish %d/%d (seed %d): %s" % (k + 1, n, c.seed, "O'TDI" if rep.ok else "o'tmadi"))
        last = (eng, rep)
        if rep.ok:
            break
    return last


def progress_printer(attempt: int, total: int):
    """SL_PROGRESS=1 bo'lsa (desktop ilova beradi) dvigatel jarayonini mashina o'qiydigan qatorlar bilan chiqaradi."""
    if not sc.env_b("SL_PROGRESS", False):
        return None
    t0 = time.time()

    def cb(*args: Any) -> None:
        print("@@PROGRESS " + json.dumps({"attempt": attempt + 1, "of": total, "elapsed": round(time.time() - t0, 1),
                                          "args": list(args)}, ensure_ascii=False, default=str), flush=True)
    return cb


# ================================================================ hisobot

def format_report(rep: sc.Report) -> str:
    lines = ["[%s] %s" % (rep.mode, rep.summary), "  %.0f soniya, %d baho" % (rep.seconds, rep.evals)]
    if "attempt" in rep.extra:
        lines.append("  urinish: %s" % rep.extra["attempt"])
    for k in ("train", "val", "test"):
        if k in rep.segments:
            lines.append("  %-5s %s" % (k, sc.fmt_stats(rep.segments[k])))
    lines.append("  DARVOZA: %s" % ("O'TDI" if rep.ok else "O'TMADI — " + "; ".join(rep.reasons)))
    if rep.extra:
        lines.append("  " + json.dumps(rep.extra, ensure_ascii=False))
    if rep.strategy:
        lines.append("  strategiya:\n    " + rep.strategy.replace("\n", "\n    "))
    return "\n".join(lines)


def tg_report(cfg: sc.Cfg, rep: sc.Report) -> None:
    te = rep.segments.get("test")
    head = "🧠 <b>Self-learning · %s</b> · %s %s" % (cfg.mode, cfg.symbol, cfg.tf)
    body = "✅ Tekshiruvdan o'tdi — savdoga qo'yildi" if rep.ok and rep.deployed else (
        "⚠️ Tekshiruvdan o'tmadi: " + "; ".join(rep.reasons[:3]))
    if rep.deployed and not rep.ok:
        body += "\n⚠️ Tekshirilmagan strategiya (SL_REQUIRE_PASS=0)"
    if te:
        body += "\n\nHoldout: %s" % sc.fmt_stats(te)
    sc.telegram(head + "\n" + body)


# ================================================================ jonli holat

class LiveState:
    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.positions: Dict[str, Dict[str, float]] = {}     # ticket -> {risk, hold}
        self.rs: List[float] = []                            # yopilgan jonli bitimlar R
        self.last_learn = 0.0
        self.paused = False
        self.seen_deals: List[int] = []

    def path(self) -> Path:
        return sc.state_path(self.cfg, "live_state.json")

    def load(self) -> None:
        try:
            d = json.loads(self.path().read_text(encoding="utf-8"))
            self.positions, self.rs = d.get("positions", {}), d.get("rs", [])
            self.last_learn, self.paused = float(d.get("last_learn", 0)), bool(d.get("paused", False))
            self.seen_deals = d.get("seen_deals", [])
        except Exception:  # noqa: BLE001
            pass

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps({"positions": self.positions, "rs": self.rs[-200:], "last_learn": self.last_learn,
                                               "paused": self.paused, "seen_deals": self.seen_deals[-400:]}), encoding="utf-8")
        except OSError:
            pass


class Learner:
    """O'rganishni fon oqimida bajaradi; tugagach yangi dvigatelni almashtirishga tayyorlaydi."""

    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[tuple] = None

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, hist: pd.DataFrame) -> None:
        def work() -> None:
            try:
                sc.log("O'RGANISH boshlandi [%s]: %d sham" % (self.cfg.mode, len(hist)))
                cand, rep = learn_repeat(self.cfg, hist)      # mavjud strategiya yangisi o'tmasa saqlanib qoladi
                sc.save_report(self.cfg, rep, hist)
                self.result = (cand, rep)
            except Exception as e:  # noqa: BLE001
                sc.log("O'RGANISH xatosi: %s\n%s" % (e, traceback.format_exc()))
                self.result = (None, None)

        self.result = None
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def take(self) -> Optional[tuple]:
        if self.busy or self.result is None:
            return None
        r, self.result = self.result, None
        return r


# ================================================================ jonli sikl

def run_live(cfg: sc.Cfg) -> None:
    import MetaTrader5 as mt5  # noqa: WPS433
    br = sc.Broker(cfg, mt5)
    br.connect()
    eng = load_engine(cfg)
    have = eng.load()
    st = LiveState(cfg)
    st.load()
    learner = Learner(cfg)
    sc.log("rejim=%s  simvol=%s %s  risk=%.2f%%  saqlangan strategiya: %s" % (cfg.mode, cfg.symbol, cfg.tf, cfg.risk_pct, "bor" if have else "yo'q"))
    sc.telegram("🧠 <b>Self-learning robot ishga tushdi</b>\nRejim: %s · %s %s · risk %.2f%%" % (cfg.mode, cfg.symbol, cfg.tf, cfg.risk_pct))
    if have:
        sc.log("joriy strategiya:\n" + eng.describe())
    due = (not have) or (time.time() - st.last_learn > cfg.relearn_hours * 3600)
    if due:
        learner.start(build_history(cfg, br))
        st.last_learn = time.time()
        st.save()
    last_bar = 0
    day_key, day_eq = "", 0.0
    stop_flag = sc.state_path(cfg, "stop.flag")
    stop_flag.unlink(missing_ok=True)
    last_status = 0.0
    while True:
        try:
            if stop_flag.exists():
                stop_flag.unlink(missing_ok=True)
                sc.log("to'xtatildi (ilova so'rovi)")
                write_status(cfg, br, eng, st, learner, day_eq, running=False)
                return
            if time.time() - last_status >= 3:
                last_status = time.time()
                write_status(cfg, br, eng, st, learner, day_eq)
            res = learner.take()
            if res is not None:
                cand, rep = res
                if rep is not None:
                    sc.append_learn_log(cfg, rep)
                    sc.log("O'RGANISH tugadi:\n" + format_report(rep))
                    tg_report(cfg, rep)
                    if cand is not None and cand.ready():
                        eng = cand
                        if rep.deployed:
                            st.paused = False
                    st.save()
            rates = mt5.copy_rates_from_pos(cfg.symbol, br._tf, 0, 1)
            cur = int(rates[-1]["time"]) if rates is not None and len(rates) else 0
            if cur and cur != last_bar:
                first = last_bar == 0
                last_bar = cur
                day_key, day_eq = _day_state(br, day_key, day_eq)
                if not first:                       # ishga tushgan zahoti yarim sham bilan savdo qilmaymiz
                    on_new_bar(cfg, br, eng, st, learner, day_eq)
            time.sleep(2)
        except KeyboardInterrupt:
            sc.log("to'xtatildi")
            return
        except Exception as e:  # noqa: BLE001
            sc.log("XATO: %s\n%s" % (e, traceback.format_exc()))
            time.sleep(15)


def write_status(cfg: sc.Cfg, br: sc.Broker, eng: Any, st: LiveState, learner: Learner, day_eq: float,
                 running: bool = True) -> None:
    """Jonli holat -> state/live_status.json (desktop ilova shu faylni o'qib panelni chizadi)."""
    try:
        ai = br.mt5.account_info()
        tk = br.mt5.symbol_info_tick(cfg.symbol)
        pos = []
        for p in br.positions():
            pos.append({"ticket": int(p.ticket), "dir": 1 if int(p.type) == int(br.mt5.POSITION_TYPE_BUY) else -1,
                        "volume": float(p.volume), "price": float(p.price_open), "sl": float(p.sl), "tp": float(p.tp),
                        "profit": float(p.profit), "time": int(p.time)})
        sc.write_json(sc.state_path(cfg, "live_status.json"), {
            "updated": time.time(), "running": running, "mode": cfg.mode, "symbol": cfg.symbol, "tf": cfg.tf,
            "login": int(ai.login) if ai else 0, "server": str(ai.server) if ai else "",
            "currency": str(getattr(ai, "currency", "")) if ai else "",
            "balance": float(ai.balance) if ai else 0.0, "equity": float(ai.equity) if ai else 0.0, "day_equity": day_eq,
            "bid": float(tk.bid) if tk else 0.0, "spread": float(tk.ask - tk.bid) if tk else 0.0, "max_spread": cfg.max_spread,
            "positions": pos, "learning": learner.busy, "ready": bool(eng.ready()), "validated": bool(eng.validated),
            "strategy": eng.describe() if eng.ready() else "", "paused": st.paused, "rs": st.rs[-60:],
            "kill_window": cfg.kill_window, "kill_sum_r": cfg.kill_sum_r, "risk_pct": cfg.risk_pct,
            "max_daily_loss_pct": cfg.max_daily_loss_pct, "require_pass": cfg.require_pass,
            "last_learn": st.last_learn, "next_learn": st.last_learn + cfg.relearn_hours * 3600})
    except Exception as e:  # noqa: BLE001
        sc.log("holat fayli yozilmadi: %s" % e)


def _day_state(br: sc.Broker, key: str, eq0: float):
    k = time.strftime("%Y-%m-%d", time.gmtime())
    return (k, br.equity()) if k != key else (key, eq0)


def sync_closed(cfg: sc.Cfg, br: sc.Broker, st: LiveState) -> None:
    """Yopilgan jonli bitimlarning R natijasini yig'adi (kill-switch uchun)."""
    m = br.mt5
    try:
        deals = m.history_deals_get(time.time() - 3 * 86400 + br.server_gmt * 3600 + 7200, time.time() + br.server_gmt * 3600 + 7200) or []
    except Exception:  # noqa: BLE001
        return
    for d in deals:
        if int(d.magic) != cfg.magic or int(d.entry) != int(m.DEAL_ENTRY_OUT) or int(d.ticket) in st.seen_deals:
            continue
        st.seen_deals.append(int(d.ticket))
        info = st.positions.pop(str(int(d.position_id)), None)
        if info and info.get("risk", 0) > 0:
            st.rs.append(round((float(d.profit) + float(getattr(d, "commission", 0)) + float(getattr(d, "swap", 0))) / info["risk"], 3))


def on_new_bar(cfg: sc.Cfg, br: sc.Broker, eng: Any, st: LiveState, learner: Learner, day_eq: float) -> None:
    df = br.closed_bars(max(eng.lookback, sc.WARMUP + 50))
    if len(df) < sc.WARMUP:
        sc.log("tarix yetarli emas (%d sham)" % len(df))
        return
    # 1) vaqt bo'yicha chiqish
    tk = br.mt5.symbol_info_tick(cfg.symbol)
    for p in br.positions():
        info = st.positions.get(str(int(p.ticket)), {})
        hold = int(info.get("hold", 96))
        if tk is not None and (int(tk.time) - int(p.time)) >= hold * cfg.tf_min * 60:
            if br.close(p):
                sc.log("vaqt bo'yicha yopildi #%s (%d sham)" % (p.ticket, hold))
    sync_closed(cfg, br, st)
    # 2) kill-switch: jonli natija strategiyani rad etsa
    if not st.paused and len(st.rs) >= cfg.kill_window and sum(st.rs[-cfg.kill_window:]) <= cfg.kill_sum_r:
        st.paused = True
        msg = "oxirgi %d jonli bitim yig'indisi %.1fR ≤ %.1fR — savdo to'xtatildi, qayta o'rganish" % (
            cfg.kill_window, sum(st.rs[-cfg.kill_window:]), cfg.kill_sum_r)
        sc.log("KILL: " + msg)
        sc.telegram("🛑 <b>Self-learning</b>: " + msg)
        st.rs = []
        if not learner.busy:
            learner.start(build_history(cfg, br))
            st.last_learn = time.time()
    # 3) rejalashtirilgan qayta o'rganish
    if not learner.busy and time.time() - st.last_learn > cfg.relearn_hours * 3600:
        learner.start(build_history(cfg, br))
        st.last_learn = time.time()
    st.save()
    # 4) kirish
    if learner.busy and not eng.ready():
        sc.log("o'rganish davom etmoqda…")
        return
    if not eng.ready():
        sc.log("strategiya yo'q (tekshiruvdan o'tmagan) — savdo yo'q")
        return
    if cfg.require_pass and not eng.validated:
        sc.log("strategiya tekshiruvdan o'tmagan — savdo yo'q")
        return
    if st.paused:
        sc.log("pauza (jonli natija yomon) — yangi strategiya kutilmoqda")
        return
    if len(br.positions()) >= cfg.max_pos:
        return
    if day_eq > 0 and br.equity() < day_eq * (1 - cfg.max_daily_loss_pct / 100.0):
        sc.log("kunlik zarar limiti — bugun yangi bitim yo'q")
        return
    sp = br.spread_px()
    if sp > cfg.max_spread:
        sc.log("spred keng (%.2f > %.2f) — o'tkazib yuborildi" % (sp, cfg.max_spread))
        return
    sig = eng.signal(df)
    if sig is None:
        return
    ok, info = br.open(sig)
    sc.log("SIGNAL %s sl=%.2f tp=%.2f hold=%d -> %s %s" % ("BUY" if sig.dir > 0 else "SELL", sig.sl, sig.tp, sig.hold,
                                                         "OCHILDI" if ok else "ochilmadi", info))
    if ok:
        known = set(st.positions)
        for p in br.positions():
            if str(int(p.ticket)) not in known:
                st.positions[str(int(p.ticket))] = {"hold": sig.hold, "risk": _risk_money(br, p, sig)}
        st.save()


def _risk_money(br: sc.Broker, p: Any, sig: sc.Signal) -> float:
    si = br.mt5.symbol_info(br.cfg.symbol)
    if si is None:
        return 0.0
    return float(p.volume) * sig.sl / (si.trade_tick_size or si.point) * si.trade_tick_value


# ================================================================ CLI

def main() -> None:
    sc.force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Self-learning robot")
    ap.add_argument("--learn", action="store_true", help="faqat o'rganish (oflayn, savdosiz, MT5 kerak emas)")
    ap.add_argument("--mode", choices=list(sc.MODES), help="SL_MODE ni bekor qiladi")
    ap.add_argument("--history", help="tarix fayli (SL_HISTORY)")
    ap.add_argument("--budget", type=float, help="o'rganish vaqti, soniya (SL_BUDGET_SEC)")
    ap.add_argument("--state", help="holat papkasi (SL_STATE_DIR)")
    ap.add_argument("--repeat", type=int, help="necha marta qayta o'rganish (SL_REPEAT); ko'p urinishda darvoza qattiqlashadi")
    ap.add_argument("--confirm", help="tasdiqlovchi instrument fayllari: 'fayl|spred|sirpanish;fayl2|spred2' (SL_CONFIRM)")
    ap.add_argument("--force", action="store_true", help="tekshiruvdan o'tmasa ham saqlash (faqat tadqiqot)")
    a = ap.parse_args()
    if a.mode:
        os.environ["SL_MODE"] = a.mode
    if a.history:
        os.environ["SL_HISTORY"] = a.history
    if a.budget:
        os.environ["SL_BUDGET_SEC"] = str(a.budget)
    if a.state:
        os.environ["SL_STATE_DIR"] = a.state
    if a.repeat:
        os.environ["SL_REPEAT"] = str(a.repeat)
    if a.confirm:
        os.environ["SL_CONFIRM"] = a.confirm
    if a.force:
        os.environ["SL_REQUIRE_PASS"] = "0"
    cfg = sc.Cfg.from_env()
    if a.learn:
        hist = build_history(cfg, None)
        eng, rep = learn_repeat(cfg, hist)
        sc.append_learn_log(cfg, rep)
        sc.save_report(cfg, rep, hist)
        print(format_report(rep))
        return
    run_live(cfg)


if __name__ == "__main__":
    main()
