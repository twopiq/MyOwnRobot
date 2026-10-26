# PyInstaller: Windows uchun desktop ilova.
#   pip install -r requirements.txt pyinstaller
#   python tools/release.py app        (avval: ilova kodi arxivi va manifest)
#   pyinstaller --noconfirm build.spec
# Natija: dist/MyOwnRobot/MyOwnRobot.exe  (robotning o'zi ham shu .exe ichida: MyOwnRobot.exe --robot ...)
#
# Ilova va robot kodi (mor) .exe ichiga kompilyatsiya qilinmaydi — ular alohida
# app/myownrobot_app.zip da turadi. Shu tufayli kod yangilanishi uchun .exe ni qayta yig'ish shart emas
# (desktop_app.py va mor/updater.py ga qarang).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

OURS = ("mor",)

datas = [(os.path.join("data", "XAUUSD_M15.csv"), "data"),
         (os.path.join("build", "app", "myownrobot_app.zip"), "app"),
         (os.path.join("build", "app", "manifest.json"), "app")]
binaries, hidden = [], []
for pkg in ("numpy", "pandas"):
    hidden += collect_submodules(pkg, filter=lambda n: ".testing" not in n and ".tests" not in n)

a = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    # o'z modullarimiz faqat kutubxona bog'liqliklarini topish uchun tahlil qilinadi, keyin PYZ dan chiqariladi
    hiddenimports=hidden + list(OURS) + ["mor.app", "mor.cli", "mor.updater", "mor.ui.update", "sqlite3", "MetaTrader5", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
                                         # kod yangilanishlarida kerak bo'lishi mumkin bo'lgan standart modullar
                                         "statistics", "urllib.request", "ssl", "hashlib", "zipfile", "tempfile",
                                         "subprocess", "shutil", "html", "csv", "importlib", "threading", "argparse",
                                         "dataclasses", "traceback", "uuid", "difflib", "itertools"],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtMultimedia", "tkinter", "pytest", "matplotlib", "sklearn", "scipy"],
)
# ilova kodi PYZ ga kirmaydi (aks holda zip'dagi yangilanish o'rniga eski kod yuklanardi)
a.pure = [m for m in a.pure if m[0].split(".")[0] not in OURS]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MyOwnRobot", console=False, upx=False,
          icon=os.path.join("mor", "assets", "app.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="MyOwnRobot", upx=False)
