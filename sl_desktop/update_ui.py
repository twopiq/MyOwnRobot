"""Yangilanish: fonda tekshirish/yuklash, menyudagi belgi, Sozlamalardagi karta va "Nima yangi" oynasi.

Ish tartibi (TTYSI Kadastr bilan bir xil):
  * ilova ochilganda (va har 6 soatda) fonda tekshiriladi;
  * kichik kod yangilanishi so'ramasdan fonda yuklanadi — menyuda "Qayta ochish" chiqadi
    (qayta ochilmasa ham, keyingi ishga tushishda o'zi kuchga kiradi);
  * kutubxonalar o'zgargan bo'lsa (to'liq paket) — "Yuklab o'rnatish" tugmasi bilan so'raladi;
  * yangilangandan keyingi birinchi ochilishda "Nima yangi" oynasi ko'rsatiladi.
"""
from __future__ import annotations

import html
import sys
import threading
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from . import __version__, updater
from . import widgets as W

PERIOD_MS = 6 * 3600 * 1000
DEFAULTS = {"kind": "github", "repo": updater.DEFAULT_REPO, "token": "", "folder": "", "auto": True}


def notes_html(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "Xatolar tuzatildi va ish barqarorligi yaxshilandi."
    out = []
    for ln in lines:
        out.append(("• " + html.escape(ln.lstrip("-*• "))) if ln.startswith(("-", "*", "•")) else "<b>%s</b>" % html.escape(ln))
    return "<br>".join(out)


class UpdateManager(QObject):
    """Holat: idle | checking | latest | available | downloading | ready | full_ready | error | source."""

    changed = Signal()
    _done = Signal(object, object, object)         # vazifa nomi, natija, xato (fon oqimidan)
    _prog = Signal(int, int)

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.state, self.message, self.info = "idle", "", None
        self.full = False
        self.pct = 0
        self.full_script: Optional[str] = None
        self._busy = False
        self._done.connect(self._finished)
        self._prog.connect(self._progress)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.check(silent=True))

    # ------------------------------------------------------------ sozlamalar
    def settings(self) -> Dict[str, Any]:
        d = dict(DEFAULTS)
        d.update(self.app.settings.ui.get("update", {}))
        d["repo"] = updater.normalize_repo(d.get("repo") or updater.DEFAULT_REPO)
        return d

    def save_settings(self, d: Dict[str, Any]) -> None:
        self.app.settings.ui["update"] = {**self.settings(), **d}
        self.app.settings.save()

    # ------------------------------------------------------------ jarayon
    def start_auto(self) -> None:
        if self.settings()["auto"]:
            QTimer.singleShot(3000, lambda: self.check(silent=True))
            self.timer.start(PERIOD_MS)

    def _run(self, name: str, fn: Callable[[Callable[[int, int], None]], Any]) -> None:
        self._busy = True

        def work() -> None:
            try:
                res = fn(lambda d, t: self._prog.emit(int(d), int(t)))
                self._done.emit(name, res, None)
            except Exception as e:  # noqa: BLE001 — foydalanuvchiga tushunarli matn ko'rsatiladi
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
            silent = name == "check" and getattr(self, "_silent", False)
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
                self._set("source", "Yangi versiya %s chiqdi. Ilova manba koddan ishlayapti — git pull bilan "
                                    "yangilang." % res.version)
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
        """Dasturni yopib qayta ochadi (to'liq paketda — almashtiruvchi skript bilan)."""
        if not self.app.close():               # jonli robot ishlasa — closeEvent tasdiq so'raydi
            return
        if self.state == "full_ready" and self.full_script:
            updater.launch_full_update(self.full_script)
        else:
            QProcess.startDetached(sys.executable, sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv)

    # ------------------------------------------------------------ menyu belgisi
    def badge(self) -> tuple:
        """(matn, ohang) yoki ("", "") — menyuda ko'rsatish uchun."""
        if self.state in ("available", "source"):
            return "Yangi versiya: %s" % self.info.version, "info"
        if self.state == "downloading":
            return "Yuklanmoqda… %d%%" % self.pct, "busy"
        if self.state in ("ready", "full_ready"):
            return "Qayta ochish → %s" % self.info.version, "good"
        return "", ""


def show_whats_new(app) -> None:
    """Yangilangandan keyingi birinchi ochilishda "Nima yangi"."""
    last = app.settings.ui.get("last_version")
    app.settings.ui["last_version"] = __version__
    app.settings.save()
    if not last or updater.version_tuple(last) >= updater.version_tuple(__version__):
        return
    box = QMessageBox(app)
    box.setWindowTitle("Dastur yangilandi")
    box.setText("<b>MyOwnRobot yangilandi: %s → %s</b><br><br>%s" % (html.escape(last), __version__,
                                                                       notes_html(updater.installed_notes(__version__))))
    box.show()


class UpdateCard(W.Card):
    """Sozlamalar sahifasidagi "Yangilanish" kartasi."""

    def __init__(self, app):
        super().__init__("Yangilanish", "Joriy versiya: %s · manba: GitHub Releases yoki tarmoq papkasi" % __version__)
        self.app = app
        self.mgr: UpdateManager = app.updates
        row = QHBoxLayout()
        self.pill = W.StatusPill("", "idle")
        row.addWidget(self.pill)
        row.addStretch(1)
        self.check_btn = QPushButton("🔄  Tekshirish")
        self.check_btn.clicked.connect(lambda: self.mgr.check(silent=False))
        self.dl_btn = QPushButton("⬇  Yuklab o'rnatish")
        self.dl_btn.setObjectName("primary")
        self.dl_btn.clicked.connect(self.mgr.download)
        self.rs_btn = QPushButton("↻  Qayta ochish")
        self.rs_btn.setObjectName("primary")
        self.rs_btn.clicked.connect(self.mgr.restart)
        for b in (self.check_btn, self.dl_btn, self.rs_btn):
            row.addWidget(b)
        self.body.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.body.addWidget(self.bar)
        self.notes = W.label("", "text2", wrap=True)
        self.body.addWidget(self.notes)

        s = self.mgr.settings()
        form = QHBoxLayout()
        form.setSpacing(16)
        c1 = QVBoxLayout()
        c1.addWidget(W.label("Manba", "text2"))
        self.kind = QComboBox()
        self.kind.addItem("GitHub Releases", "github")
        self.kind.addItem("Tarmoq / mahalliy papka", "folder")
        self.kind.setCurrentIndex(0 if s["kind"] != "folder" else 1)
        c1.addWidget(self.kind)
        self.auto = QCheckBox("Avtomatik tekshirish va yuklash")
        self.auto.setChecked(bool(s["auto"]))
        c1.addWidget(self.auto)
        form.addLayout(c1, 1)
        self.gh = QWidget()
        g = QVBoxLayout(self.gh)
        g.setContentsMargins(0, 0, 0, 0)
        g.addWidget(W.label("Repozitoriy (egasi/nomi)", "text2"))
        self.repo = QLineEdit(s["repo"])
        g.addWidget(self.repo)
        g.addWidget(W.label("Token (yopiq repozitoriy uchun, faqat o'qish)", "text2"))
        self.token = QLineEdit(s["token"])
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setToolTip(updater.TOKEN_HELP)
        g.addWidget(self.token)
        form.addWidget(self.gh, 2)
        self.fd = QWidget()
        f = QVBoxLayout(self.fd)
        f.setContentsMargins(0, 0, 0, 0)
        f.addWidget(W.label("Papka (update.json joylashgan)", "text2"))
        fr = QHBoxLayout()
        self.folder = QLineEdit(s["folder"])
        fb = QPushButton("📁")
        fb.setFixedWidth(44)
        fb.clicked.connect(self._browse)
        fr.addWidget(self.folder, 1)
        fr.addWidget(fb)
        f.addLayout(fr)
        f.addStretch(1)
        form.addWidget(self.fd, 2)
        self.body.addLayout(form)
        self.kind.currentIndexChanged.connect(self._kind)
        for w in (self.repo, self.token, self.folder):
            w.editingFinished.connect(self.save)
        self.auto.toggled.connect(lambda *_: self.save())
        self.mgr.changed.connect(self.refresh)
        self._kind()
        self.refresh()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Yangilanishlar papkasi", self.folder.text())
        if d:
            self.folder.setText(d)
            self.save()

    def _kind(self) -> None:
        gh = self.kind.currentData() == "github"
        self.gh.setVisible(gh)
        self.fd.setVisible(not gh)
        self.save()

    def save(self) -> None:
        self.mgr.save_settings({"kind": self.kind.currentData(), "repo": updater.normalize_repo(self.repo.text()),
                                "token": self.token.text().strip(), "folder": self.folder.text().strip(),
                                "auto": self.auto.isChecked()})

    def refresh(self) -> None:
        m = self.mgr
        tone = {"checking": "busy", "downloading": "busy", "latest": "good", "available": "info", "source": "info",
                "ready": "good", "full_ready": "good", "error": "critical"}.get(m.state, "idle")
        text = {"idle": "Tekshirilmagan", "checking": "Tekshirilmoqda…", "latest": "Eng yangi versiya",
                "available": "Yangi versiya bor", "source": "Yangi versiya bor", "downloading": "Yuklanmoqda… %d%%" % m.pct,
                "ready": "Qayta ochishga tayyor", "full_ready": "O'rnatishga tayyor", "error": "Xato"}.get(m.state, "")
        self.pill.set(text, tone)
        self.bar.setVisible(m.state == "downloading")
        self.bar.setValue(m.pct)
        self.check_btn.setEnabled(m.state not in ("checking", "downloading"))
        self.dl_btn.setVisible(m.state == "available")
        self.rs_btn.setVisible(m.state in ("ready", "full_ready"))
        msg = html.escape(m.message).replace("\n", "<br>")
        if m.info is not None and m.state in ("available", "ready", "full_ready", "source", "downloading"):
            msg += "<br><br>" + notes_html(m.info.notes)
        self.notes.setText(msg)
