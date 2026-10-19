# MyOwnRobot — o'zi o'rganadigan savdo robot (MT5, Python)

Robot tarix faylini (yoki MT5 tarixini) oladi, **o'zi qayta-qayta test qilib** kirish strategiyasini shakllantiradi,
uni **tegilmagan oxirgi davrda** tekshiradi va faqat u yerda foydali chiqsagina DEMO hisobda savdo qiladi.
Har `SL_RELEARN_HOURS` soatda (standart 168 = haftada bir) yangi ma'lumot bilan qayta o'rganadi.

Standart: **XAUUSD, M15**, faqat **DEMO** hisob (`SL_DEMO_ONLY=0` bilan o'chiriladi — tavsiya etilmaydi).

## Uch rejim (`SL_MODE`) — kodda bir-biriga bog'liq emas

| SL_MODE | Fayl | Qanday "o'zi shakllantiradi" |
|---|---|---|
| `genetic` | `sl_genetic.py` | 1–3 shartli kirish qoidalarini (RSI, EMA masofa, Bollinger, yorilish, soat…) evolyutsiya bilan yaratadi; SL/TP/ushlash muddatini ham o'zi tanlaydi |
| `optimizer` | `sl_optimizer.py` | 3 oila (trend_pullback, donchian, bb_revert) parametrlarini walk-forward bilan qayta optimallaydi (18 oy train → 3 oy ko'r test, qo'shni parametrlar bilan silliqlash) |
| `ml` | `sl_ml.py` | XGBoost: har sham uchun "BUY/SELL xarajatlardan keyin TP ga yetadimi" ehtimolini o'rganadi, chegarani validatsiyada tanlaydi, `state/ml_model.joblib` ga saqlaydi |

Har dvigatel faqat `sl_core.py` (tarix, indikator, simulyator, MT5 qatlami) dan foydalanadi, boshqa dvigatelni import qilmaydi
(testlar tekshiradi). `selflearn_robot.py` faqat tanlangan rejimning modulini yuklaydi.

## Haddan tashqari moslashishdan himoya
* Tarix vaqt bo'yicha **train 60% / validatsiya 20% / holdout 20%** (oxirgi, eng yangi). Holdout qidiruvda ishtirok etmaydi.
* Simulyator xarajatlarni hisoblaydi: spred (`SL_SPREAD`, 0.30$), sirpanish (0.05$); signal sham yopilishida, kirish keyingi ochilishda; SL va TP bir shamda tegsa — SL.
* **Qabul darvozasi**: holdout'da kamida 40 bitim, kutilma ≥ +0.05R, PF ≥ 1.10, t ≥ 1.0, validatsiya va train foydali, holdout choraklarining ≥ 50% foydali. O'tmasa robot **savdo qilmaydi** (`SL_REQUIRE_PASS=0` faqat tadqiqot uchun).
* Jonli himoya: oxirgi 20 bitim yig'indisi ≤ −6R bo'lsa to'xtab qayta o'rganadi; kunlik zarar limiti; keng spredda kirmaydi; risk % bo'yicha lot.

## Haqiqiy tarixdagi natija (XAUUSD M15, 2022-01 … 2026-10, ~113 ming sham) — halol hisobot
Uchala rejim ham o'rganish davrida chiroyli ko'rinadi, lekin tegilmagan davrda ustunlik yo'q — darvoza hammasini rad etdi:

| Rejim | Train (o'rganilgan) | Holdout / OOS | Darvoza |
|---|---|---|---|
| genetic | +0.27R, t=3.7 | +0.03R, t=0.3 | o'tmadi |
| optimizer | +0.14R (oxirgi oyna) | +0.03R, t=0.5 (13 oyna, 552 bitim) | o'tmadi |
| ml | win 65%, +0.41R | −0.01R, t=−0.1 | o'tmadi |

Ya'ni oltin M15 da spred+sirpanishdan keyin bu usullar o'zi hech narsa "ixtiro qila olmadi" — bu normal va aynan shu uchun
himoya bor. Boshqa tarix (boshqa instrument/TF), ko'proq xususiyat, `SL_SPREAD` ni kamaytirish (ECN hisob) bilan sinab ko'ring.
Foyda kafolati yo'q; robot faqat demo uchun.

## O'rnatish
1. `python -m venv .venv_bot && .venv_bot\Scripts\pip install -r requirements.txt` (Python 3.12).
2. Oflayn tadqiqot (MT5 kerak emas):
   ```
   python selflearn_robot.py --learn --mode genetic   --history data/XAUUSD_M15.csv
   python selflearn_robot.py --learn --mode optimizer --history data/XAUUSD_M15.csv
   python selflearn_robot.py --learn --mode ml        --history data/XAUUSD_M15.csv
   ```
   Natija `state/` papkasida (`learn_log.jsonl`, strategiya fayli). `--budget 600` — ko'proq vaqt, `--force` — o'tmasa ham saqlash (tadqiqot).
3. Jonli (MT5 terminali ochiq, demo hisobga kirilgan): `set SL_MODE=optimizer` va `python selflearn_robot.py`.
   *Robot No.1* dasturida: Jonli → Python robotlar → skript `selflearn_robot.py` + qo'shimcha fayllar `sl_*.py` (+ ixtiyoriy tarix CSV),
   sozlamalarga `SL_MODE=genetic` va `SL_HISTORY=XAUUSD_M15.csv`.
4. Boshqa tarix fayli: `python make_history.py kirish.pkl|csv chiqish.csv M15` (MT4 eksporti, epoch, pkl, parquet o'qiladi;
   fayl vaqti serverda bo'lsa `SL_HISTORY_GMT=2`).

## Sozlamalar (env)
`SL_MODE`, `SL_HISTORY`, `SL_HISTORY_GMT`, `SL_HISTORY_YEARS`, `SL_TF`, `SL_RISK_PCT` (0.5), `SL_SPREAD` (0.30), `SL_SLIPPAGE` (0.05),
`SL_MAX_SPREAD` (0.80), `SL_MAX_POS` (1), `SL_MAGIC`, `SL_RELEARN_HOURS` (168), `SL_BUDGET_SEC` (240), `SL_REQUIRE_PASS` (1),
`SL_DEMO_ONLY` (1), `SL_SEED`, `SL_MAX_DAILY_LOSS_PCT` (3), `SL_KILL_WINDOW`/`SL_KILL_SUM_R`, darvoza: `SL_MIN_TEST_TRADES`,
`SL_MIN_EXP_R`, `SL_MIN_PF`, `SL_MIN_T`, `SL_MIN_POS_CHUNKS`; `SL_OPT_SAMPLES`; ML: `SL_ML_SL`, `SL_ML_RR`, `SL_ML_HOLD`.
Telegram: `TELEGRAM_ENABLED`, `TG_BOT_TOKEN`, `TG_CHAT_ID` (Robot No.1 o'zi beradi).

## Testlar
`python -m pytest tests -q` (simulyator qo'lda yozilgan etalon bilan mos, lookahead yo'qligi, yashirin qonuniyatni genetik topishi,
soxta MT5 bilan lot/buyurtma, dvigatellar mustaqilligi).
