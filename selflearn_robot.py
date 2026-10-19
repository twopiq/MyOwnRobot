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
    stored = load_bar_store(cfg)
    if stored is not None and len(stored):
        sc.log("saqlangan jonli shamlar: %d, %s .. %s" % (len(stored), stored.index[0], stored.index[-1]))
    parts = [x for x in (base, stored, recent) if x is not None and len(x)]
    if not parts:
        raise RuntimeError("tarix yo'q: SL_HISTORY faylini bering yoki MT5 ulanishini tekshiring")
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return sc.limit_years(df, cfg.history_years)


# ================================================================ jonli ma'lumot ombori

def bar_store_path(cfg: sc.Cfg) -> Path:
    safe = "".join(ch if ch.isalnum() else "_" for ch in cfg.symbol)
    return sc.state_path(cfg, "bars_%s_%s.csv" % (safe, cfg.tf))


def load_bar_store(cfg: sc.Cfg) -> Optional[pd.DataFrame]:
    """Jonli rejimda yig'ilgan yopilgan shamlar (UTC). Robot qayta ishga tushsa ham saqlanadi va o'sib boradi."""
    p = bar_store_path(cfg)
    if not p.exists():
        return None
    try:
        return sc.read_history_file(str(p))
    except Exception as e:  # noqa: BLE001
        sc.log("shamlar ombori o'qilmadi: %s" % e)
        return None


def store_bars(cfg: sc.Cfg, df: pd.DataFrame, last: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
    """Ombordagi oxirgi shamdan yangilarini qo'shadi; yangi oxirgi vaqtni qaytaradi."""
    if df is None or not len(df):
        return last
    new = df if last is None else df[df.index > last]
    if not len(new):
        return last
    p = bar_store_path(cfg)
    head = not p.exists()
    try:
        new[["open", "high", "low", "close", "volume"]].to_csv(p, mode="a", header=head, index_label="time")
    except OSError as e:
        sc.log("shamlar saqlanmadi: %s" % e)
        return last
    return new.index[-1]


def sync_bar_store(cfg: sc.Cfg, br: sc.Broker) -> Optional[pd.Timestamp]:
    """Ishga tushganda: MT5 dagi barcha mavjud shamlarni omborga qo'shib qo'yadi (bo'shliq qolmasligi uchun)."""
    old = load_bar_store(cfg)
    last = old.index[-1] if old is not None and len(old) else None
    try:
        last = store_bars(cfg, br.closed_bars(60000), last)
    except Exception as e:  # noqa: BLE001
        sc.log("MT5 shamlari omborga yozilmadi: %s" % e)
    return last


def log_live_trade(cfg: sc.Cfg, row: Dict[str, Any]) -> None:
    p = sc.state_path(cfg, "live_trades.csv")
    head = not p.exists()
    try:
        with open(p, "a", encoding="utf-8") as f:
            if head:
                f.write(",".join(row) + "\n")
            f.write(",".join(str(v) for v in row.values()) + "\n")
    except OSError:
        pass


def _data_key(cfg: sc.Cfg, hist: pd.DataFrame) -> str:
    """Urinishlar hisobi kaliti: rejim, instrument, TF, tarix boshi va oxirgi shamning haftasi.
    Bir xil ma'lumotda hisob davom etadi (qayta-qayta sinash — darvoza qattiqlashadi); jonli rejimda yangi hafta
    ma'lumoti kelganda holdout yangilanadi va hisob qaytadan boshlanadi. Xarajatlar (spred) kalitga kirmaydi:
    spredni o'zgartirib qayta sinash ham "yana bir urinish" hisoblanadi."""
    first = str(hist.index[0]) if len(hist) else ""
    week = "%d-W%02d" % tuple(hist.index[-1].isocalendar()[:2]) if len(hist) else ""
    return "%s|%s|%s|%s|%s" % (cfg.mode, cfg.symbol, cfg.tf, first, week)


def attempts_done(cfg: sc.Cfg, hist: pd.DataFrame) -> int:
    try:
        d = json.loads(sc.state_path(cfg, "attempts.json").read_text(encoding="utf-8"))
        return int(d.get(_data_key(cfg, hist), 0))
    except (OSError, ValueError):
        return 0


def _save_attempts(cfg: sc.Cfg, hist: pd.DataFrame, n: int) -> None:
    p = sc.state_path(cfg, "attempts.json")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d[_data_key(cfg, hist)] = n
    try:
        sc.write_json(p, d)
    except OSError:
        pass


def learn_repeat(cfg: sc.Cfg, hist: pd.DataFrame, base: Any = None, forever: Optional[bool] = None,
                 on_attempt: Any = None):
    """Yangi seed va variant bilan qayta-qayta o'rganadi; birinchi o'tgan urinishda to'xtaydi.

    Urinishlar shu ma'lumot uchun state/attempts.json da hisoblanadi (tugmani qayta bosish ham, ilovani qayta ochish ham
    hisobni davom ettiradi). Har urinish yangi seed oladi — natija takrorlanmaydi; darvozaning t-chegarasi esa
    jami urinishlar soniga qarab Bonferroni bo'yicha qattiqlashadi (ko'p urinishda tasodifiy "omad" o'tib ketmasligi uchun).
    forever=True: cfg.repeat e'tiborsiz, o'tguncha yoki state/stop.flag paydo bo'lguncha davom etadi.
    Qaytaradi: (dvigatel, hisobot)."""
    forever = cfg.forever if forever is None else forever
    done = attempts_done(cfg, hist)
    n = max(1, cfg.repeat)
    stop = sc.state_path(cfg, "stop.flag")
    last: Optional[tuple] = None
    k = 0
    while True:
        j = done + k + 1                                         # shu ma'lumotdagi jami urinish raqami
        trials = max(cfg.trials, j if forever else done + n)
        c = dataclasses.replace(cfg, seed=cfg.seed + done + k, trials=trials, attempt=done + k)
        eng = load_engine(c)
        eng.load()
        cb = progress_printer(k, 0 if forever else n)
        rep = eng.learn(hist, progress=cb) if cb else eng.learn(hist)
        rep.extra["attempt"] = ("%d" % j) if forever else "%d/%d" % (k + 1, n)
        rep.extra["attempt_no"] = j
        rep.extra["min_t"] = round(sc.eff_min_t(c), 3)
        _save_attempts(cfg, hist, j)
        te = rep.segments.get("test") or {}
        sc.log("urinish %d (seed %d, t chegarasi %.2f): %s%s" % (
            j, c.seed, sc.eff_min_t(c), "O'TDI" if rep.ok else "o'tmadi",
            (" — holdout %+.3fR, t=%.2f" % (te.get("exp", 0), te.get("t", 0))) if te else ""))
        if sc.env_b("SL_PROGRESS", False):
            print("@@ATTEMPT " + json.dumps({"no": j, "ok": bool(rep.ok), "exp": te.get("exp"), "t": te.get("t"),
                                             "n": te.get("n"), "need_t": rep.extra["min_t"]}), flush=True)
        if on_attempt is not None:
            on_attempt(eng, rep)
        last = (eng, rep)
        k += 1
        if rep.ok or (not forever and k >= n):
            break
        if stop.exists():
            stop.unlink(missing_ok=True)
            sc.log("uzluksiz o'rganish to'xtatildi (%d urinish)" % j)
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
        self.spreads: List[float] = []                       # har yangi shamda kuzatilgan spred
        self.champ: Dict[str, Any] = {}                      # joriy (tekshirilgan) strategiya: holdout t, vaqt, urinish
        self.cycles = 0                                      # jonli o'rganish sikllari soni
        self.last_result: Dict[str, Any] = {}

    def path(self) -> Path:
        return sc.state_path(self.cfg, "live_state.json")

    def load(self) -> None:
        try:
            d = json.loads(self.path().read_text(encoding="utf-8"))
            self.positions, self.rs = d.get("positions", {}), d.get("rs", [])
            self.last_learn, self.paused = float(d.get("last_learn", 0)), bool(d.get("paused", False))
            self.seen_deals = d.get("seen_deals", [])
            self.spreads, self.champ = d.get("spreads", []), d.get("champ", {})
            self.cycles, self.last_result = int(d.get("cycles", 0)), d.get("last_result", {})
        except Exception:  # noqa: BLE001
            pass

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps({"positions": self.positions, "rs": self.rs[-200:], "last_learn": self.last_learn,
                                               "paused": self.paused, "seen_deals": self.seen_deals[-400:],
                                               "spreads": self.spreads[-3000:], "champ": self.champ, "cycles": self.cycles,
                                               "last_result": self.last_result}), encoding="utf-8")
        except OSError:
            pass


class Learner:
    """O'rganishni fon oqimida bajaradi; tugagach yangi dvigatelni almashtirishga tayyorlaydi."""

    def __init__(self, cfg: sc.Cfg):
        self.cfg = cfg
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[tuple] = None
        self.finished_at = 0.0

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, hist: pd.DataFrame, cfg: Optional[sc.Cfg] = None) -> None:
        c = cfg or self.cfg

        def work() -> None:
            try:
                sc.log("O'RGANISH boshlandi [%s]: %d sham, spred %.2f, t ≥ %.2f dan" % (c.mode, len(hist), c.spread, c.min_t))
                cand, rep = learn_repeat(c, hist, forever=False)   # mavjud strategiya yangisi o'tmasa qoladi
                sc.save_report(c, rep, hist)
                self.result = (cand, rep)
            except Exception as e:  # noqa: BLE001
                sc.log("O'RGANISH xatosi: %s\n%s" % (e, traceback.format_exc()))
                self.result = (None, None)
            self.finished_at = time.time()

        self.result = None
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def take(self) -> Optional[tuple]:
        if self.busy or self.result is None:
            return None
        r, self.result = self.result, None
        return r


# ================================================================ jonli sikl

def live_learn_cfg(cfg: sc.Cfg, st: LiveState) -> sc.Cfg:
    """Jonli o'rganish sozlamasi: (1) xarajat — jonli kuzatilgan spred (median) sozlamadagidan katta bo'lsa o'shani oladi;
    (2) chempion: tekshirilgan strategiya yangi bo'lsa (SL_RELEARN_HOURS dan yosh), raqib uning holdout t sidan
    yuqori natija ko'rsatishi shart — aks holda joriy strategiya almashtirilmaydi va saqlanmaydi."""
    import statistics
    c = cfg
    if len(st.spreads) >= 100:
        obs = float(statistics.median(st.spreads[-2000:]))
        if obs > c.spread:
            c = dataclasses.replace(c, spread=round(obs, 5))
    ch = st.champ
    if ch and ch.get("t") is not None and time.time() - float(ch.get("time", 0)) < cfg.relearn_hours * 3600:
        c = dataclasses.replace(c, min_t=max(c.min_t, float(ch["t"])))
    return c


def start_learning(cfg: sc.Cfg, br: sc.Broker, st: LiveState, learner: Learner) -> None:
    learner.start(build_history(cfg, br), live_learn_cfg(cfg, st))
    st.last_learn = time.time()
    st.cycles += 1
    st.save()


def run_live(cfg: sc.Cfg) -> None:
    import MetaTrader5 as mt5  # noqa: WPS433
    br = sc.Broker(cfg, mt5)
    br.connect()
    stored_to = sync_bar_store(cfg, br)
    eng = load_engine(cfg)
    have = eng.load()
    st = LiveState(cfg)
    st.load()
    learner = Learner(cfg)
    sc.log("rejim=%s  simvol=%s %s  risk=%.2f%%  saqlangan strategiya: %s" % (cfg.mode, cfg.symbol, cfg.tf, cfg.risk_pct, "bor" if have else "yo'q"))
    sc.telegram("🧠 <b>Self-learning robot ishga tushdi</b>\nRejim: %s · %s %s · risk %.2f%%" % (cfg.mode, cfg.symbol, cfg.tf, cfg.risk_pct))
    if have:
        sc.log("joriy strategiya:\n" + eng.describe())
    due = (not have) or cfg.live_continuous or (time.time() - st.last_learn > cfg.relearn_hours * 3600)
    if due:
        start_learning(cfg, br, st, learner)
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
                    te = rep.segments.get("test") or {}
                    st.last_result = {"time": time.time(), "ok": bool(rep.ok), "deployed": bool(rep.deployed),
                                      "t": te.get("t"), "exp": te.get("exp"), "n": te.get("n"),
                                      "attempt": rep.extra.get("attempt_no"), "need_t": rep.extra.get("min_t")}
                    if rep.deployed or rep.ok:
                        tg_report(cfg, rep)
                    if cand is not None and cand.ready() and (rep.deployed or not eng.ready()):
                        eng = cand
                        if rep.deployed:
                            st.paused = False
                            if rep.ok:
                                st.champ = {"t": te.get("t"), "exp": te.get("exp"), "time": time.time(),
                                            "attempt": rep.extra.get("attempt_no"), "strategy": rep.strategy}
                                sc.log("YANGI STRATEGIYA joriy qilindi (holdout t=%.2f)" % (te.get("t") or 0))
                    st.save()
            # uzluksiz jonli o'rganish: sikl tugagach pauza va yangi ma'lumot bilan keyingisi
            if cfg.live_continuous and not learner.busy and learner.result is None \
                    and time.time() - learner.finished_at >= cfg.learn_pause_sec:
                start_learning(cfg, br, st, learner)
            rates = mt5.copy_rates_from_pos(cfg.symbol, br._tf, 0, 1)
            cur = int(rates[-1]["time"]) if rates is not None and len(rates) else 0
            if cur and cur != last_bar:
                first = last_bar == 0
                last_bar = cur
                day_key, day_eq = _day_state(br, day_key, day_eq)
                stored_to = store_bars(cfg, br.closed_bars(5), stored_to)
                try:
                    st.spreads = (st.spreads + [round(br.spread_px(), 5)])[-3000:]
                except Exception:  # noqa: BLE001
                    pass
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
            "last_learn": st.last_learn, "next_learn": (learner.finished_at + cfg.learn_pause_sec) if cfg.live_continuous
            else st.last_learn + cfg.relearn_hours * 3600,
            "continuous": cfg.live_continuous, "cycles": st.cycles, "last_result": st.last_result, "champ": st.champ,
            "spread_obs": (sorted(st.spreads[-2000:])[len(st.spreads[-2000:]) // 2] if len(st.spreads) >= 20 else None),
            "spread_cfg": cfg.spread, "bars_stored": _count_lines(bar_store_path(cfg))})
    except Exception as e:  # noqa: BLE001
        sc.log("holat fayli yozilmadi: %s" % e)


_LINES: Dict[str, tuple] = {}


def _count_lines(p: Path) -> int:
    """Ombordagi shamlar soni (fayl o'zgarmasa keshdan)."""
    try:
        m = p.stat().st_mtime
    except OSError:
        return 0
    k = str(p)
    if k not in _LINES or _LINES[k][0] != m:
        with open(p, "rb") as f:
            _LINES[k] = (m, max(0, sum(1 for _ in f) - 1))
    return _LINES[k][1]


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
        pnl = float(d.profit) + float(getattr(d, "commission", 0)) + float(getattr(d, "swap", 0))
        r = round(pnl / info["risk"], 3) if info and info.get("risk", 0) > 0 else None
        if r is not None:
            st.rs.append(r)
        log_live_trade(cfg, {"close_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "position": int(d.position_id),
                             "mode": cfg.mode, "profit": round(pnl, 2), "R": "" if r is None else r,
                             "strategy_t": (st.champ or {}).get("t", "")})


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
            start_learning(cfg, br, st, learner)
    # 3) rejalashtirilgan qayta o'rganish; tekshirilgan strategiya yo'q bo'lsa — kutmasdan, uzluksiz qayta o'rganish
    need = (not eng.ready()) or (cfg.require_pass and not eng.validated) or st.paused
    if not learner.busy and not cfg.live_continuous and (
            time.time() - st.last_learn > cfg.relearn_hours * 3600 or (cfg.until_pass and need)):
        start_learning(cfg, br, st, learner)
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
    ap.add_argument("--forever", action="store_true",
                    help="darvozadan o'tguncha uzluksiz qayta o'rganish (SL_FOREVER); to'xtatish: state/stop.flag")
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
    if a.forever:
        os.environ["SL_FOREVER"] = "1"
    cfg = sc.Cfg.from_env()
    if a.learn:
        hist = build_history(cfg, None)
        sc.state_path(cfg, "stop.flag").unlink(missing_ok=True)

        def each(_eng: Any, r: sc.Report) -> None:          # har urinish jurnalga va hisobotga yoziladi
            sc.append_learn_log(cfg, r)
            sc.save_report(cfg, r, hist)
        eng, rep = learn_repeat(cfg, hist, on_attempt=each)
        print(format_report(rep))
        return
    run_live(cfg)


if __name__ == "__main__":
    main()
