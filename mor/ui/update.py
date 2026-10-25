"""Yangilanish: fonda tekshirish/yuklash. Kichik kod yangilanishi fonda yuklanadi (qayta ochilganda kuchga kiradi);
kutubxonalar o'zgargan bo'lsa to'liq paket so'raladi."""
from __future__ import annotations

import html
import sys
import threading
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .. import __version__, updater

PERIOD_MS = 6 * 3600 * 1000
DEFAULTS = {"kind": "github", "repo": updater.DEFAULT_REPO, "token": "", "folder": "", "auto": True}


def notes_html(text: str) -> str:
    lines = [html.escape(x.strip()) for x in (text or "").splitlines() if x.strip()]
    return "<br>".join(lines) or "Yaxshilanishlar va tuzatishlar."


class UpdateManager(QObject):
    """Holat: idle | checking | latest | available | downloading | ready | full_ready | error | source."""

    changed = Signal()
    _done = Signal(object, object, object)
    _prog = Signal(int, int)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.state, self.message, self.info = "idle", "", None
        self.full, self.pct, self.full_script = False, 0, None
        self._busy, self._silent = False, False
        self._done.connect(self._finished)
        self._prog.connect(self._progress)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.check(silent=True))

    def settings(self) -> Dict[str, Any]:
        d = dict(DEFAULTS)
        d.update(self.win.settings.ui.get("update", {}))
        d["repo"] = updater.normalize_repo(d.get("repo") or updater.DEFAULT_REPO)
        return d

    def save_settings(self, d: Dict[str, Any]) -> None:
        self.win.settings.ui["update"] = {**self.settings(), **d}
        self.win.settings.save()

    def start_auto(self) -> None:
        if self.settings()["auto"]:
            QTimer.singleShot(3000, lambda: self.check(silent=True))
            self.timer.start(PERIOD_MS)

    def _run(self, name: str, fn: Callable[[Callable[[int, int], None]], Any]) -> None:
        self._busy = True

        def work() -> None:
            try:
                self._done.emit(name, fn(lambda d, t: self._prog.emit(int(d), int(t))), None)
            except Exception as e:  # noqa: BLE001
                self._done.emit(name, None, e)
        threading.Thread(target=work, daemon=True).start()

    def _set(self, state: str, message: str = "") -> None:
        self.state, self.message = state, message
        self.changed.emit()

    def check(self, silent: bool = False) -> None:
        if self._busy or self.state in ("ready", "full_ready"):
            return
        try:
            src = updater.make_source(self.settings())
        except Exception as e:  # noqa: BLE001
            self._set("error", updater.friendly_error(e))
            return
        self._silent = silent
        self._set("checking", "Tekshirilmoqda…")
        self._run("check", lambda _p: updater.check(src))

    def download(self) -> None:
        if self._busy or self.info is None:
            return
        info, full = self.info, self.full
        self.pct = 0
        self._set("downloading", "Yuklanmoqda…")
        self._run("full" if full else "code",
                  lambda p: updater.prepare_full_update(info, p) if full else updater.install_code_update(info, p))

    def _progress(self, done: int, total: int) -> None:
        self.pct = int(done * 100 / total) if total else 0
        self.changed.emit()

    def _finished(self, name: str, res: Any, err: Any) -> None:
        self._busy = False
        if err is not None:
            silent = name == "check" and self._silent
            self._set("idle" if silent else "error", "" if silent else updater.friendly_error(err))
            return
        if name == "check":
            self.info = res
            if res is None:
                self._set("latest", "Sizda eng yangi versiya: %s" % __version__)
                return
            man = updater.bundled_manifest()
            self.full = res.needs_full(man["libs"] if man else None) or updater.is_broken(res.version)
            if not updater.is_frozen():
                self._set("source", "Yangi versiya %s chiqdi. Ilova manba koddan ishlayapti — git pull bilan yangilang." % res.version)
            elif not self.full and updater.downloaded(res.version):
                self._set("ready", "Versiya %s yuklangan — qayta ochilganda kuchga kiradi." % res.version)
            else:
                self._set("available", "Yangi versiya %s mavjud%s." % (
                    res.version, " (to'liq paket, kutubxonalar yangilangan)" if self.full else ""))
                if not self.full and self.settings()["auto"]:
                    self.download()
        elif name == "code":
            self._set("ready", "Versiya %s yuklandi — qayta ochilganda kuchga kiradi." % self.info.version)
        elif name == "full":
            self.full_script = res
            self._set("full_ready", "To'liq paket yuklandi. Dastur yopilib, yangilanadi va qayta ochiladi.")

    def restart(self) -> None:
        if not self.win.close():
            return
        if self.state == "full_ready" and self.full_script:
            updater.launch_full_update(self.full_script)
        else:
            QProcess.startDetached(sys.executable, sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv)

    def badge(self) -> tuple:
        if self.state in ("available", "source"):
            return "Yangi versiya: %s" % self.info.version, "info"
        if self.state == "downloading":
            return "Yuklanmoqda… %d%%" % self.pct, "busy"
        if self.state in ("ready", "full_ready"):
            return "Qayta ochish → %s" % self.info.version, "good"
        return "", ""
