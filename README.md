# MyOwnRobot 2.0

Mustaqil o'rganadigan savdo roboti (RL) va Windows desktop ilovasi. **Faqat DEMO hisob uchun.**
Foyda va'da qilinmaydi: robot natijalari ma'lumotlarga bog'liq, ilova esa o'zi halol baholab beradi.

## Qanday ishlaydi
1. **Ma'lumotlar** — MT5 formatidagi CSV (M1/M5/M15…), MT5 dan yuklash, iqtisodiy kalendar CSV. Hammasi SQLite bazada (`%LOCALAPPDATA%\MyOwnRobot`).
2. **O'rganish** — Double DQN (sof numpy). Robot tarixiy shamlarda tajriba qiladi: kutadi, sotib oladi, soladi, yopadi.
   Narx: spred + sirpanish; stop-loss = 1.5×ATR (=1R); mukofot = R.
3. **Xotira** — har bir bitim saqlanadi. Yaxshilari (R ≥ 1, "namuna") va xatolari (R ≤ −1) belgilanadi va o'qitishda belgilangan ulushda qayta o'ynaladi.
4. **Qonuniyatlar** — bitimlardan "qaysi sharoitda yutadi/yutqazadi" qoidalari qidiriladi, ko'rilmagan davrda tekshiriladi. Tasdiqlangan "qochish" qoidalari kirishni to'sadi.
5. **Halol baho** — har instrument xronologik 70/15/15 (o'rganish/validatsiya/test). Eng yaxshi model validatsiyada tanlanadi, test faqat yakuniy hisobot uchun. Jonli savdoga ruxsat: n≥100, kutilma ≥0.05R, t≥2.0 (yoki qo'lda `allow_unvalidated`).
6. **Jonli savdo** — MT5 demo, risk % bo'yicha lot, kunlik zarar chegarasi, kill-switch.

## Ishga tushirish
```
pip install -r requirements.txt
python desktop_app.py                      # ilova
python desktop_app.py --robot import fayl.csv --symbol EURUSD --tf M15
python desktop_app.py --robot train --epochs 50 --symbols EURUSD,XAUUSD
python -m pytest tests
```

## Reliz
`mor/__init__.py` dagi versiyani oshiring va `main` ga yuboring — GitHub Actions Windows `.exe` yig'adi, sinaydi va relizga chiqaradi.
Ilova kodi (`mor/`) `.exe` dan alohida zip'da, shuning uchun kutubxonalar o'zgarmasa dastur o'zi yangilanadi.
