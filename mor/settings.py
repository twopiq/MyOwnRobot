"""Sozlamalar: JSON fayl (%LOCALAPPDATA%/MyOwnRobot/settings.json). Maydonlar tavsifi UI ni ham shakllantiradi."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .paths import user_dir


@dataclass
class Field:
    key: str
    label: str
    group: str
    kind: str                      # int | float | bool | str | secret | choice | path
    default: Any
    help: str = ""
    lo: float = 0
    hi: float = 1e9
    step: float = 1
    choices: Tuple[str, ...] = ()
    suffix: str = ""


FIELDS: List[Field] = [
    Field("tf", "Taymfreym", "O'qitish", "choice", "M15", "Agent ishlaydigan sham davri", choices=("M5", "M15", "M30", "H1")),
    Field("symbols", "Instrumentlar", "O'qitish", "str", "", "Vergul bilan (bo'sh = bazadagi barcha datasetlar)"),
    Field("epochs", "Epoxalar", "O'qitish", "int", 200, "Bitta ishga tushirishda epoxalar soni", lo=1, hi=100000),
    Field("envs", "Parallel muhitlar", "O'qitish", "int", 16, "Bir vaqtda o'ynaladigan epizodlar", lo=1, hi=128),
    Field("episode_len", "Epizod uzunligi", "O'qitish", "int", 1500, "Har epizodda shamlar soni", lo=200, hi=20000, step=100),
    Field("eval_every", "Tasdiqlash davri", "O'qitish", "int", 10, "Har necha epoxada val tekshiriladi", lo=1, hi=1000),
    Field("lr", "O'rganish tezligi", "Model", "float", 0.0003, "", lo=1e-6, hi=0.1, step=0.0001),
    Field("gamma", "Diskont (γ)", "Model", "float", 0.99, "Kelajak mukofotining og'irligi", lo=0.5, hi=0.999, step=0.01),
    Field("hidden", "Yashirin qatlamlar", "Model", "str", "128,128", "Neyron tarmoq o'lchami (vergul bilan)"),
    Field("sl_atr", "Stop-loss (ATR)", "Muhit", "float", 1.5, "1R = shuncha ATR", lo=0.5, hi=5, step=0.1),
    Field("max_hold", "Eng ko'p ushlash", "Muhit", "int", 96, "Sham", lo=4, hi=1000),
    Field("share_elite", "Namunalar ulushi", "Xotira", "float", 0.1, "Qayta o'ynashda foydali bitimlar ulushi", lo=0, hi=0.5, step=0.05),
    Field("share_mistake", "Xatolar ulushi", "Xotira", "float", 0.1, "Qayta o'ynashda katta zarar bitimlari ulushi", lo=0, hi=0.5, step=0.05),
    Field("seed", "Seed", "Model", "int", 0, "", lo=0, hi=10**6),
    Field("symbol", "Savdo simvoli", "Jonli savdo", "str", "XAUUSD", "MT5 dagi aniq nom"),
    Field("risk_pct", "Bitim xavfi", "Jonli savdo", "float", 0.25, "Hisobning foizi (1R)", lo=0.01, hi=5, step=0.05, suffix=" %"),
    Field("max_daily_loss_pct", "Kunlik zarar chegarasi", "Jonli savdo", "float", 2.0, "", lo=0.1, hi=20, step=0.5, suffix=" %"),
    Field("kill_r", "Avtomatik to'xtatish", "Jonli savdo", "float", -6.0, "Oxirgi 20 bitim yig'indisi (R)", lo=-50, hi=-1, step=1),
    Field("allow_unvalidated", "Tekshiruvdan o'tmagan siyosat", "Jonli savdo", "bool", False,
          "Darvozadan o'tmagan siyosat bilan DEMO'da savdo qilishga ruxsat (faqat tadqiqot uchun)"),
    Field("terminal", "MT5 terminal yo'li", "MT5 hisob", "path", "", "terminal64.exe"),
    Field("login", "Hisob raqami", "MT5 hisob", "str", "", "DEMO hisob"),
    Field("password", "Parol", "MT5 hisob", "secret", ""),
    Field("server", "Server", "MT5 hisob", "str", ""),
]
DEFAULTS: Dict[str, Any] = {f.key: f.default for f in FIELDS}


class Settings:
    def __init__(self, path: Optional[str] = None):
        from pathlib import Path
        self.path = Path(path) if path else user_dir() / "settings.json"
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self.ui: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in raw.get("values", {}).items():
                if k in DEFAULTS:
                    self.data[k] = v
            self.ui = raw.get("ui", {})
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"values": self.data, "ui": self.ui}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def __getitem__(self, k: str) -> Any:
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k: str, v: Any) -> None:
        self.data[k] = v

    def train_cfg(self):
        from .trainer import TrainCfg
        d = self.data
        syms = [s.strip().upper() for s in str(d["symbols"]).split(",") if s.strip()]
        hid = tuple(int(x) for x in str(d["hidden"]).replace(" ", "").split(",") if x) or (128, 128)
        return TrainCfg(tf=d["tf"], symbols=syms, epochs=int(d["epochs"]), envs=int(d["envs"]), episode_len=int(d["episode_len"]),
                        eval_every=int(d["eval_every"]), hidden=hid, lr=float(d["lr"]), gamma=float(d["gamma"]),
                        sl_atr=float(d["sl_atr"]), max_hold=int(d["max_hold"]), share_elite=float(d["share_elite"]),
                        share_mistake=float(d["share_mistake"]), seed=int(d["seed"]))

    def live_cfg(self):
        from .live import LiveCfg
        d = self.data
        try:
            login = int(str(d["login"]).strip() or 0)
        except ValueError:
            login = 0
        return LiveCfg(symbol=d["symbol"], tf=d["tf"], risk_pct=float(d["risk_pct"]),
                       max_daily_loss_pct=float(d["max_daily_loss_pct"]), kill_r=float(d["kill_r"]), terminal=d["terminal"],
                       login=login, password=d["password"], server=d["server"])
