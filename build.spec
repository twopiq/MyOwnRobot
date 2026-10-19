# PyInstaller: Windows uchun desktop ilova.
#   pip install -r requirements.txt pyinstaller
#   pyinstaller --noconfirm build.spec
# Natija: dist/MyOwnRobot/MyOwnRobot.exe  (robotning o'zi ham shu .exe ichida: MyOwnRobot.exe --robot ...)
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hidden = [(os.path.join("data", "XAUUSD_M15.csv"), "data")], [], []
for pkg in ("xgboost", "sklearn"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + ["selflearn_robot", "sl_core", "sl_genetic", "sl_optimizer", "sl_ml", "joblib",
                            "MetaTrader5", "matplotlib.backends.backend_qtagg", "statistics"],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtMultimedia", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MyOwnRobot", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="MyOwnRobot", upx=False)
