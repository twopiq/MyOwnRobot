"""MyOwnRobot ishga tushiruvchi "qobiq".

    python desktop_app.py                        — ilovani ochish
    python desktop_app.py --robot [...]          — buyruq qatori rejimi (mor.cli: import / train / info)
    python desktop_app.py --self-test out.json   — oynani yaratib tekshiradi (CI uchun)

O'rnatilgan (.exe) dasturda ilova kodi (`mor` paketi) .exe ichida emas, alohida zip arxivda turadi. Ishga tushishda eng
yangi mos kod tanlanadi:
  1. %LOCALAPPDATA%/MyOwnRobot/updates/<versiya>/myownrobot_app.zip — yuklangan yangilanishlar
     (faqat kutubxonalari — "libs" — shu .exe bilan bir xil bo'lganlari);
  2. aks holda .exe bilan kelgan app/myownrobot_app.zip.
Yangilangan kod ishga tushmasa, u "buzilgan" (BROKEN) deb belgilanadi va o'rnatilgan kod ishlatiladi.

Bu faylni kod yangilanishi o'zgartira olmaydi — u faqat to'liq qayta yig'ishda yangilanadi.
"""

import json
import os
import sys

APP_ZIP = "myownrobot_app.zip"
_OURS = ("mor",)


def _vt(v):
    return tuple(int("".join(c for c in p if c.isdigit()) or 0) for p in v.strip().lstrip("vV").split("."))


def _updates_dir():
    # mor/updater.py dagi updates_dir() bilan bir xil bo'lishi kerak
    if os.environ.get("MYOWNROBOT_UPDATES_DIR"):
        return os.environ["MYOWNROBOT_UPDATES_DIR"]
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MyOwnRobot", "updates")


def _candidates():
    """(versiya, zip yo'li, yangilanish papkasi yoki None) — eng yangisi birinchi. Manba koddan — bo'sh ro'yxat."""
    base = getattr(sys, "_MEIPASS", None)
    man_path = os.path.join(base, "app", "manifest.json") if base else None
    if not man_path or not os.path.exists(man_path):
        return []
    with open(man_path, encoding="utf-8") as f:
        bundled = json.load(f)
    out = [(_vt(bundled["version"]), os.path.join(base, "app", APP_ZIP), None)]
    upd = _updates_dir()
    if os.path.isdir(upd):
        for name in os.listdir(upd):
            d = os.path.join(upd, name)
            try:
                if os.path.exists(os.path.join(d, "BROKEN")):
                    continue
                with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
                z = os.path.join(d, APP_ZIP)
                if m.get("libs") == bundled.get("libs") and os.path.exists(z):
                    out.append((_vt(m["version"]), z, d))
            except (OSError, ValueError, KeyError):
                continue
    out.sort(key=lambda c: c[0], reverse=True)
    return out


def _load(gui: bool = True):
    """Ilova kodini eng yangi ishlaydigan arxivdan yuklaydi; manbani qaytaradi ("source" yoki zip yo'li)."""
    cands = _candidates()
    if not cands:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        return "source"
    last_error = None
    for _, zpath, upd_dir in cands:
        sys.path.insert(0, zpath)
        try:
            import mor
            import mor.cli  # noqa: F401
            if gui:
                import mor.app  # noqa: F401  (butun ilova importi — buzuq arxiv shu yerda aniqlanadi)
            os.environ["MYOWNROBOT_RUNNING_VERSION"] = mor.__version__
            return zpath
        except Exception as e:  # yangilanish buzilgan — keyingisiga o'tamiz
            last_error = e
            sys.path.remove(zpath)
            for mod in [m for m in sys.modules if m.split(".")[0] in _OURS]:
                del sys.modules[mod]
            if upd_dir:
                try:
                    with open(os.path.join(upd_dir, "BROKEN"), "w", encoding="utf-8") as f:
                        f.write(repr(e))
                except OSError:
                    pass
    raise last_error


def main() -> int:
    robot = len(sys.argv) > 1 and sys.argv[1] == "--robot"
    source = _load(gui=not robot)
    if robot:
        import mor.cli
        return mor.cli.main(sys.argv[2:])
    import mor.app
    argv = list(sys.argv)
    rc = mor.app.run_gui(argv)
    if len(argv) > 2 and argv[1] == "--self-test":          # manba ma'lumotini qo'shamiz
        with open(argv[2], encoding="utf-8") as f:
            d = json.load(f)
        d["source"] = source
        with open(argv[2], "w", encoding="utf-8") as f:
            json.dump(d, f)
    return rc


def _guarded() -> int:
    try:
        return main()
    except BaseException:
        import traceback
        if len(sys.argv) > 2 and sys.argv[1] == "--self-test":      # CI: xatoni faylga yozamiz (oynasiz .exe da konsol yo'q)
            with open(sys.argv[2] + ".err", "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return 1                                              # oyna chiqmasin (PyInstaller xato oynasi CI ni osib qo'yadi)
        raise


if __name__ == "__main__":
    rc = _guarded()
    if len(sys.argv) > 2 and sys.argv[1] == "--self-test":
        sys.stdout.flush()
        os._exit(rc or 0)                                         # oqimlar/taymerlar jarayonni ushlab turmasin
    sys.exit(rc)
