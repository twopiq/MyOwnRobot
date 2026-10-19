"""Robot sozlamalari (env o'zgaruvchilari) — ilovadagi forma shu ro'yxatdan quriladi va desktop_settings.json ga saqlanadi."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def app_dir() -> Path:
    """Ilova ma'lumotlari papkasi: .exe yonida (PyInstaller) yoki repozitoriy ildizida."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Robot fayllari va namunaviy tarix turgan papka (.exe ichida — _MEIPASS)."""
    return Path(getattr(sys, "_MEIPASS", app_dir()))


@dataclass
class Field:
    key: str            # env nomi
    label: str
    group: str
    kind: str           # float | int | bool | str | choice | file
    default: Any
    help: str
    lo: float = 0.0
    hi: float = 1e9
    step: float = 1.0
    choices: Tuple[str, ...] = ()
    suffix: str = ""


GROUPS = [
    ("asosiy", "Asosiy", "Instrument, rejim va tarix fayli"),
    ("risk", "Risk va himoya", "Har bitim xavfi, kunlik zarar limiti, avtomatik to'xtash"),
    ("learn", "O'rganish", "Vaqt byudjeti, qayta o'rganish va urinishlar"),
    ("gate", "Qabul darvozasi", "Strategiya savdoga qo'yilishi uchun holdout shartlari"),
    ("cost", "Xarajatlar", "Simulyatsiyada hisobga olinadigan spred va sirpanish"),
    ("mt5", "MetaTrader 5", "Terminal, hisob va Telegram xabarnomalari"),
]

FIELDS: List[Field] = [
    Field("SL_MODE", "Rejim", "asosiy", "choice", "genetic", "Strategiyani qanday usul bilan shakllantirish",
          choices=("genetic", "optimizer", "ml")),
    Field("SL_SYMBOL", "Simvol", "asosiy", "str", "XAUUSD", "MT5 dagi instrument nomi (masalan XAUUSD, EURUSD)"),
    Field("SL_TF", "Taymfreym", "asosiy", "choice", "M15", "Sham davri", choices=("M1", "M5", "M15", "M30", "H1", "H4")),
    Field("SL_HISTORY", "Tarix fayli", "asosiy", "file", "data/XAUUSD_M15.csv",
          "CSV / PKL / Parquet tarix. Jonli rejimda MT5 dagi so'nggi shamlar bilan birlashtiriladi"),
    Field("SL_HISTORY_GMT", "Fayl vaqti GMT", "asosiy", "float", 0.0, "Fayldagi vaqt GMT ga nisbatan (Dukascopy = 0, MT server = 2)",
          lo=-12, hi=14, step=0.5, suffix=" soat"),
    Field("SL_HISTORY_YEARS", "Tarix chuqurligi", "asosiy", "float", 0.0, "Faqat oxirgi N yil (0 — hammasi)", lo=0, hi=50,
          step=0.5, suffix=" yil"),

    Field("SL_RISK_PCT", "Bitim xavfi", "risk", "float", 0.5, "Har bitimda balansning necha foizi xavf ostida (SL gacha)",
          lo=0.05, hi=5, step=0.05, suffix=" %"),
    Field("SL_MAX_DAILY_LOSS_PCT", "Kunlik zarar limiti", "risk", "float", 3.0,
          "Kun boshidagi equity'dan shuncha foiz tushsa — bugun yangi bitim ochilmaydi", lo=0.5, hi=20, step=0.5, suffix=" %"),
    Field("SL_MAX_POS", "Maks. ochiq pozitsiya", "risk", "int", 1, "Bir vaqtda ochiq bitimlar soni", lo=1, hi=10),
    Field("SL_MAX_SPREAD", "Maks. spred", "risk", "float", 0.80, "Spred shundan keng bo'lsa kirilmaydi (narx birligida)",
          lo=0, hi=100, step=0.05),
    Field("SL_KILL_WINDOW", "Kill-switch oynasi", "risk", "int", 20, "Oxirgi N jonli bitim kuzatiladi", lo=5, hi=200,
          suffix=" bitim"),
    Field("SL_KILL_SUM_R", "Kill-switch chegarasi", "risk", "float", -6.0,
          "Oxirgi N bitim yig'indisi shundan past bo'lsa savdo to'xtab qayta o'rganadi", lo=-100, hi=0, step=0.5, suffix=" R"),
    Field("SL_DEMO_ONLY", "Faqat DEMO hisob", "risk", "bool", True, "O'chirish tavsiya etilmaydi: real hisobda savdo xavfli"),
    Field("SL_REQUIRE_PASS", "Faqat tekshirilgan strategiya", "risk", "bool", True,
          "Darvozadan o'tmagan strategiya bilan savdo qilinmaydi (o'chirish — faqat tadqiqot uchun)"),

    Field("SL_BUDGET_SEC", "O'rganish vaqti", "learn", "int", 240, "Bitta o'rganish sikli uchun vaqt byudjeti", lo=20, hi=7200,
          step=10, suffix=" s"),
    Field("SL_RELEARN_HOURS", "Qayta o'rganish davri", "learn", "float", 168.0, "Jonli rejimda har necha soatda qayta o'rganadi",
          lo=1, hi=2000, step=1, suffix=" soat"),
    Field("SL_REPEAT", "Urinishlar soni", "learn", "int", 1,
          "Yangi seed bilan necha marta o'rganish; ko'p urinishda darvoza t-chegarasi qattiqlashadi (Bonferroni)", lo=1, hi=20),
    Field("SL_FOREVER", "Uzluksiz o'rganish", "learn", "bool", True,
          "O'rganish tugmasi bosilganda robot darvozadan o'tguncha (yoki to'xtatilguncha) qayta-qayta, har safar yangi "
          "variant bilan o'rganadi"),
    Field("SL_LEARN_UNTIL_PASS", "Jonli: o'tguncha qayta o'rganish", "learn", "bool", True,
          "Jonli rejimda tekshirilgan strategiya bo'lmasa haftani kutmasdan darhol qayta o'rganadi"),
    Field("SL_SEED", "Seed", "learn", "int", 7, "Tasodifiy sonlar boshlang'ich qiymati", lo=0, hi=10 ** 6),
    Field("SL_CONFIRM", "Tasdiqlovchi instrumentlar", "learn", "str", "",
          "Boshqa tarix fayllari: 'fayl|spred|sirpanish;fayl2|spred2' — strategiya ularda ham foydali bo'lishi kerak"),

    Field("SL_MIN_TEST_TRADES", "Min. holdout bitimlari", "gate", "int", 40, "", lo=5, hi=2000),
    Field("SL_MIN_EXP_R", "Min. kutilma", "gate", "float", 0.05, "Bir bitimdan o'rtacha natija", lo=-1, hi=2, step=0.01,
          suffix=" R"),
    Field("SL_MIN_PF", "Min. profit faktor", "gate", "float", 1.10, "Foyda / zarar nisbati", lo=0.5, hi=5, step=0.05),
    Field("SL_MIN_T", "Min. t-statistika", "gate", "float", 1.0, "Natija tasodif emasligi ishonchi", lo=0, hi=5, step=0.1),
    Field("SL_MIN_POS_CHUNKS", "Foydali bo'laklar ulushi", "gate", "float", 0.5,
          "Holdout to'rt bo'lagining kamida shuncha qismi foydali bo'lishi", lo=0, hi=1, step=0.05),

    Field("SL_SPREAD", "Spred", "cost", "float", 0.30, "Simulyatsiyadagi spred (narx birligida, XAUUSD uchun $)", lo=0, hi=50,
          step=0.01),
    Field("SL_SLIPPAGE", "Sirpanish", "cost", "float", 0.05, "Kirish/SL dagi sirpanish", lo=0, hi=50, step=0.01),

    Field("SL_TERMINAL", "terminal64.exe yo'li", "mt5", "file", "",
          "Bir nechta MT5 ochiq bo'lsa aniq terminalni ko'rsating (bo'sh — kutubxona o'zi tanlaydi)"),
    Field("SL_LOGIN", "Hisob raqami", "mt5", "int", 0, "Terminal boshqa hisobga ulangan bo'lsa robot to'xtaydi (0 — tekshirilmaydi)",
          lo=0, hi=10 ** 12),
    Field("SL_MAGIC", "Magic raqam", "mt5", "int", 0, "Robot bitimlari belgisi (0 — rejimga qarab avtomatik)", lo=0, hi=10 ** 9),
    Field("TELEGRAM_ENABLED", "Telegram xabarlari", "mt5", "bool", False, "O'rganish natijasi va kill-switch haqida xabar"),
    Field("TG_BOT_TOKEN", "Telegram bot token", "mt5", "str", "", "@BotFather bergan token"),
    Field("TG_CHAT_ID", "Telegram chat ID", "mt5", "str", "", "Xabar yuboriladigan chat"),
]

BY_KEY = {f.key: f for f in FIELDS}

MODES = {
    "genetic": ("Genetik evolyutsiya", "🧬",
                "1–3 shartli kirish qoidalarini (RSI, EMA masofa, Bollinger, yorilish, soat…) evolyutsiya bilan yaratadi. "
                "SL, TP va ushlash muddatini ham o'zi tanlaydi."),
    "optimizer": ("Walk-forward optimizator", "📈",
                  "3 ta strategiya oilasi (trend pullback, Donchian, Bollinger qaytish) parametrlarini 18 oy o'rganish → "
                  "3 oy ko'r test oynalarida qayta-qayta optimallaydi."),
    "ml": ("Mashinali o'rganish (XGBoost)", "🤖",
           "Har sham uchun «BUY/SELL xarajatlardan keyin TP ga yetadimi» ehtimolini o'rganadi; chegarani validatsiyada tanlaydi."),
}


class Settings:
    def __init__(self, path: Optional[Path] = None, state: Optional[Path] = None):
        self.path = path or app_dir() / "desktop_settings.json"
        self._state = state
        self.values: Dict[str, Any] = {f.key: f.default for f in FIELDS}
        self.ui: Dict[str, Any] = {"theme": "dark"}
        self.load()

    def load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in d.get("env", {}).items():
            if k in BY_KEY:
                self.values[k] = v
        self.ui.update(d.get("ui", {}))

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps({"env": self.values, "ui": self.ui}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def get(self, key: str) -> Any:
        return self.values.get(key, BY_KEY[key].default if key in BY_KEY else None)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    def reset(self) -> None:
        self.values = {f.key: f.default for f in FIELDS}

    def state_dir(self) -> Path:
        return self._state or app_dir() / "state"

    def resolve(self, p: str) -> str:
        """Nisbiy yo'l: avval ilova papkasi, keyin .exe ichidagi namunaviy fayllar."""
        if not p:
            return ""
        q = Path(p)
        if q.is_absolute():
            return str(q)
        for base in (app_dir(), bundle_dir()):
            if (base / q).exists():
                return str(base / q)
        return str(app_dir() / q)

    def env(self, **override: Any) -> Dict[str, str]:
        """Robot jarayoni uchun muhit: sozlamalar + SL_STATE_DIR + SL_PROGRESS."""
        out = dict(os.environ)
        vals = {**self.values, **override}
        for f in FIELDS:
            v = vals.get(f.key, f.default)
            if f.kind == "bool":
                out[f.key] = "1" if v else "0"
            elif f.key in ("SL_MAGIC", "SL_LOGIN") and not v:
                out.pop(f.key, None)
            elif f.kind == "file":
                if v:
                    out[f.key] = self.resolve(str(v))
                else:
                    out.pop(f.key, None)
            elif v in ("", None):
                out.pop(f.key, None)
            else:
                out[f.key] = str(v)
        out["SL_STATE_DIR"] = str(self.state_dir())
        out["SL_PROGRESS"] = "1"
        out["PYTHONIOENCODING"] = "utf-8"
        out["PYTHONUNBUFFERED"] = "1"
        return out
