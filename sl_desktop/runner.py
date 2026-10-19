"""Robotni alohida jarayonda ishga tushirish (QProcess) va uning chiqishini signallarga aylantirish."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .settings import app_dir, bundle_dir


def robot_command(args: List[str]) -> List[str]:
    """.exe ichida — o'sha .exe ni --robot bilan; manba koddan — selflearn_robot.py ni."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--robot"] + args
    return [sys.executable, "-u", str(bundle_dir() / "selflearn_robot.py")] + args


class RobotProcess(QObject):
    line = Signal(str)
    progress = Signal(dict)
    started = Signal()
    finished = Signal(int, str)          # chiqish kodi, oxirgi muhim qator

    def __init__(self, name: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.name = name
        self.proc: Optional[QProcess] = None
        self._buf = ""
        self._tail: List[str] = []
        self._stop_file: Optional[Path] = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def start(self, args: List[str], env: Dict[str, str]) -> None:
        if self.running:
            return
        cmd = robot_command(args)
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        p.setWorkingDirectory(str(app_dir()))
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        p.setProcessEnvironment(qenv)
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(self._done)
        p.errorOccurred.connect(self._error)
        self._buf, self._tail = "", []
        self._stop_file = Path(env.get("SL_STATE_DIR", "state")) / "stop.flag"
        self.proc = p
        self.line.emit("$ " + " ".join('"%s"' % a if " " in a else a for a in cmd))
        p.start(cmd[0], cmd[1:])
        self.started.emit()

    def stop(self, graceful: bool = False) -> None:
        """graceful: jonli robotga stop.flag yoziladi (holatni saqlab chiqadi), 10 s ichida chiqmasa — majburan."""
        if not self.running:
            return
        if graceful and self._stop_file is not None:
            try:
                self._stop_file.parent.mkdir(parents=True, exist_ok=True)
                self._stop_file.write_text("stop", encoding="utf-8")
                QTimer.singleShot(10000, self._kill)
                return
            except OSError:
                pass
        self._kill()

    def _kill(self) -> None:
        if self.running:
            self.proc.kill()

    def _read(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._buf += data.replace("\r\n", "\n")
        *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            self._handle(ln)

    def _handle(self, ln: str) -> None:
        if ln.startswith("@@PROGRESS "):
            try:
                self.progress.emit(json.loads(ln[len("@@PROGRESS "):]))
            except ValueError:
                pass
            return
        if ln.strip():
            self._tail = (self._tail + [ln])[-30:]
        self.line.emit(ln)

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.line.emit("Jarayon ishga tushmadi: %s" % (self.proc.errorString() if self.proc else ""))
            self.finished.emit(-1, "Jarayon ishga tushmadi")

    def _done(self, code: int, _status) -> None:
        if self._buf:
            self._handle(self._buf)
            self._buf = ""
        self.finished.emit(int(code), self.error_summary())

    def error_summary(self) -> str:
        """Traceback bo'lsa — oxirgi xato qatori, aks holda oxirgi qator."""
        for ln in reversed(self._tail):
            s = ln.strip()
            if s.startswith(("RuntimeError", "SystemExit", "ModuleNotFoundError", "ImportError", "ValueError",
                             "FileNotFoundError", "OSError")) or "Error:" in s:
                return s
        return self._tail[-1] if self._tail else ""


# Ma'lum xatolar: matndagi belgi -> foydalanuvchiga tushunarli izoh va nima qilish kerakligi
HINTS = [
    ("UnicodeEncodeError", "Konsol kodirovkasi maxsus belgini (≥, × …) chiqara olmadi. Ilovani yangilang — "
                           "1.1.1 dan boshlab robot chiqishi UTF-8 da."),
    ("MetaTrader5", "MetaTrader5 Python kutubxonasi yo'q: Windows'da `pip install MetaTrader5` (yoki .exe versiyasidan foydalaning)."),
    ("MT5 initialize", "MT5 terminali ochilmagan yoki topilmadi. Terminalni oching, hisobga kiring yoki "
                       "Jonli savdo → terminal64.exe yo'lini ko'rsating."),
    ("faqat DEMO", "Terminal REAL hisobga ulangan. Robot faqat DEMO hisobda ishlaydi — terminalda demo hisobga kiring."),
    ("boshqa hisobga", "Terminal boshqa hisobga ulangan. «Hisob raqami» maydonini yoki terminal yo'lini tekshiring."),
    ("simvol topilmadi", "Brokerda bunday simvol yo'q. Simvol nomini MT5 dagi «Market Watch» bilan solishtiring (masalan XAUUSD.m)."),
    ("tarix yo'q", "Tarix fayli topilmadi va MT5 tarixi ham yo'q. O'rganish sahifasida tarix faylini tanlang."),
    ("tarix fayli topilmadi", "Ko'rsatilgan tarix fayli mavjud emas — yo'lni tekshiring."),
    ("MemoryError", "Xotira yetmadi. «Tarix chuqurligi» ni kamaytiring (masalan 3 yil) yoki boshqa dasturlarni yoping."),
    ("PermissionError", "Faylga yozish ruxsati yo'q. Dasturni yozish mumkin bo'lgan papkaga ko'chiring."),
]


def explain_error(text: str) -> str:
    for key, hint in HINTS:
        if key.lower() in (text or "").lower():
            return hint
    return ""
