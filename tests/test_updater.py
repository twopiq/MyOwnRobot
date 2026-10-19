"""Yangilanish tizimi: reliz fayllari, papka manbasidan o'rnatish, SHA-256, qobiqning versiya tanlashi va qaytishi."""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sl_desktop import updater  # noqa: E402


def test_version_compare_and_repo_normalize():
    assert updater.version_tuple("v1.10.0") > updater.version_tuple("1.9.9")
    assert updater.normalize_repo("https://github.com/twopiq/MyOwnRobot.git") == "twopiq/MyOwnRobot"
    assert updater.normalize_repo("") == updater.DEFAULT_REPO


def _repo_copy(tmp_path, version, patch=None):
    repo = tmp_path / f"repo_{version}"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "build", "dist", "__pycache__", "state", "data",
                                                              "docs", "tests"))
    init = repo / "sl_desktop" / "__init__.py"
    init.write_text(init.read_text().replace(f'"{updater.current_version()}"', f'"{version}"'))
    if patch:
        patch(repo)
    return repo


def _publish(tmp_path, version, notes="yangi"):
    repo = _repo_copy(tmp_path, version)
    out = tmp_path / "net"
    subprocess.run([sys.executable, str(repo / "tools" / "release.py"), "publish", str(out), "--notes",
                    notes + "\n\nCo-Authored-By: x"], check=True, capture_output=True)
    return out


def test_release_zip_contains_app_and_robot(tmp_path):
    net = _publish(tmp_path, "99.0.0")
    man = json.loads((net / "update.json").read_text())
    assert man["notes"] == "yangi" and man["app_zip"] == "myownrobot_app-99.0.0.zip"
    with zipfile.ZipFile(net / man["app_zip"]) as z:
        names = set(z.namelist())
    assert {"sl_desktop/__init__.py", "sl_desktop/app.py", "sl_desktop/updater.py", "selflearn_robot.py", "sl_core.py",
            "sl_genetic.py", "sl_optimizer.py", "sl_ml.py"} <= names
    assert "desktop_app.py" not in names                       # qobiq yangilanmaydi


def test_folder_update_install(tmp_path, monkeypatch):
    monkeypatch.setenv("MYOWNROBOT_UPDATES_DIR", str(tmp_path / "upd"))
    net = _publish(tmp_path, "99.0.0", "Yangilanish tizimi")
    src = updater.FolderSource(str(net))
    info = updater.check(src)
    assert info is not None and info.version == "99.0.0" and info.notes == "Yangilanish tizimi"
    assert updater.check(src, current="99.0.0") is None
    man = json.loads((net / "update.json").read_text())
    assert not info.needs_full(man["libs"]) and info.needs_full("boshqa")
    seen = []
    target = updater.install_code_update(info, lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1]
    with zipfile.ZipFile(os.path.join(target, "myownrobot_app.zip")) as z:
        assert '__version__ = "99.0.0"' in z.read("sl_desktop/__init__.py").decode()
    assert updater.downloaded("99.0.0")["version"] == "99.0.0"
    assert updater.installed_notes("99.0.0") == "Yangilanish tizimi"


def test_corrupted_download_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MYOWNROBOT_UPDATES_DIR", str(tmp_path / "upd"))
    net = _publish(tmp_path, "99.0.1")
    man = json.loads((net / "update.json").read_text())
    with open(net / man["app_zip"], "ab") as f:
        f.write(b"buzuq")
    info = updater.check(updater.FolderSource(str(net)))
    with pytest.raises(RuntimeError, match="SHA-256"):
        updater.install_code_update(info)
    assert not (tmp_path / "upd" / "99.0.1").exists()


def _zip_of(repo, dest):
    sys.path.insert(0, str(repo / "tools"))
    try:
        subprocess.run([sys.executable, str(repo / "tools" / "release.py"), "app"], check=True, capture_output=True)
    finally:
        sys.path.pop(0)
    shutil.copy(repo / "build" / "app" / "myownrobot_app.zip", dest)
    return json.loads((repo / "build" / "app" / "manifest.json").read_text())


def _shell(meipass, upd, cwd):
    """desktop_app.py ni .exe dagidek (sys._MEIPASS bilan) robot rejimida ishga tushiradi; yuklangan versiyani qaytaradi."""
    code = ("import sys, runpy; sys._MEIPASS = %r; sys.argv = ['x', '--robot', '--help']\n"
            "try:\n    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "import sl_desktop, selflearn_robot, os\n"
            "print('VER', sl_desktop.__version__, os.environ.get('MYOWNROBOT_RUNNING_VERSION'), selflearn_robot.__file__)"
            % (str(meipass), str(ROOT / "desktop_app.py")))
    env = {**os.environ, "MYOWNROBOT_UPDATES_DIR": str(upd), "PYTHONPATH": ""}
    out = subprocess.run([sys.executable, "-c", code], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr[-1500:]
    return next(ln for ln in out.stdout.splitlines() if ln.startswith("VER")).split()


def test_shell_prefers_newest_update_and_skips_broken(tmp_path):
    mei = tmp_path / "mei" / "app"
    mei.mkdir(parents=True)
    base = _repo_copy(tmp_path, "1.0.5")
    man = _zip_of(base, mei / "myownrobot_app.zip")
    (mei / "manifest.json").write_text(json.dumps(man))
    upd = tmp_path / "upd"
    good = _repo_copy(tmp_path, "2.0.0")
    d = upd / "2.0.0"
    d.mkdir(parents=True)
    _zip_of(good, d / "myownrobot_app.zip")
    (d / "manifest.json").write_text(json.dumps({"version": "2.0.0", "libs": man["libs"]}))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    v = _shell(tmp_path / "mei", upd, cwd)
    assert v[1] == "2.0.0" and v[2] == "2.0.0" and "upd" in v[3]

    # buzilgan yangilanish: import xatosi -> BROKEN belgisi va o'rnatilgan kodga qaytish
    bad = _repo_copy(tmp_path, "3.0.0", patch=lambda r: (r / "sl_core.py").write_text("raise ImportError('buzuq')\n"))
    d3 = upd / "3.0.0"
    d3.mkdir()
    _zip_of(bad, d3 / "myownrobot_app.zip")
    (d3 / "manifest.json").write_text(json.dumps({"version": "3.0.0", "libs": man["libs"]}))
    v = _shell(tmp_path / "mei", upd, cwd)
    assert v[1] == "2.0.0" and (d3 / "BROKEN").exists()

    # kutubxonalari boshqa yangilanish e'tiborga olinmaydi
    (d / "manifest.json").write_text(json.dumps({"version": "2.0.0", "libs": "boshqa"}))
    v = _shell(tmp_path / "mei", upd, cwd)
    assert v[1] == "1.0.5"


def test_update_card_and_manager(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("MYOWNROBOT_UPDATES_DIR", str(tmp_path / "upd"))
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    net = _publish(tmp_path, "99.0.0", "Yangi grafiklar")
    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(tmp_path / "s.json", state=tmp_path / "st"))
    w.updates.timer.stop()
    w.updates.save_settings({"kind": "folder", "folder": str(net), "auto": False})
    w.updates.check(silent=False)
    loop = QEventLoop()
    for _ in range(100):
        if w.updates.state not in ("checking", "idle"):
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert w.updates.state == "source" and w.updates.info.version == "99.0.0"   # manba koddan: faqat xabar
    w.refresh_nav()
    assert w.upd_btn.isVisibleTo(w) and "99.0.0" in w.upd_btn.text()
    w.go("settings")
    assert "Yangi grafiklar" in w.pages["settings"].update_card.notes.text()
    w.close()


def test_manager_downloads_code_update_in_background(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("MYOWNROBOT_UPDATES_DIR", str(tmp_path / "upd"))
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from sl_desktop.app import MainWindow
    from sl_desktop.settings import Settings
    net = _publish(tmp_path, "99.0.0")
    libs = json.loads((net / "update.json").read_text())["libs"]
    monkeypatch.setattr(updater, "is_frozen", lambda: True)                      # o'rnatilgan dasturdek
    monkeypatch.setattr(updater, "bundled_manifest", lambda: {"version": "1.0.0", "libs": libs})
    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(tmp_path / "s.json", state=tmp_path / "st"))
    w.updates.timer.stop()
    w.updates.save_settings({"kind": "folder", "folder": str(net), "auto": True})
    w.updates.check(silent=True)
    loop = QEventLoop()
    for _ in range(200):
        if w.updates.state in ("ready", "error"):
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert w.updates.state == "ready", w.updates.message
    assert (tmp_path / "upd" / "99.0.0" / "myownrobot_app.zip").exists()
    w.refresh_nav()
    assert "Qayta ochish" in w.upd_btn.text()
    w.close()
