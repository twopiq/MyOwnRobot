"""Dasturni yangilash.

Ikki xil yangilanish:
  * kod yangilanishi (kichik, ~100 KB) - kutubxonalar (Qt, XGBoost, pandas ...) o'zgarmagan bo'lsa.
    Yangi kod %LOCALAPPDATA%/MyOwnRobot/updates/<versiya>/ ga yuklanadi va keyingi ishga
    tushishda desktop_app.py uni o'zidagi koddan ustun qo'yadi;
  * to'liq yangilanish (~100 MB) - kutubxonalar o'zgargan bo'lsa (manifestdagi "libs" farq qiladi).
    Zip yuklanadi, dastur yopilgach PowerShell skript papkani almashtirib, dasturni qayta ochadi.

Manba: GitHub Releases (ochiq repo yoki token bilan) yoki tarmoq/mahalliy papka. Ikkalasida ham
update.json manifesti bo'ladi:
  {"version": "0.2.0", "libs": "ab12...", "notes": "...",
   "app_zip": "myownrobot_app-0.2.0.zip", "app_sha256": "...",
   "full_zip": "MyOwnRobot_Windows.zip", "full_sha256": "..."}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass

from . import __version__

DEFAULT_REPO = "twopiq/MyOwnRobot"
MANIFEST_NAME = "update.json"
APP_ZIP_NAME = "myownrobot_app.zip"
RETRIES = 3            # tarmoq uzilsa yuklashni qayta urinish soni


class UpdateError(RuntimeError):
    """Foydalanuvchiga tushunarli matnli yangilanish xatosi."""


def friendly_error(e: Exception) -> str:
    """Texnik xatoni oddiy tilga o'giradi."""
    if isinstance(e, UpdateError):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "Yangilanish serveriga kirish rad etildi (token noto'g'ri yoki muddati o'tgan)."
        if e.code == 404:
            return "Yangilanish topilmadi."
        return f"Server xatosi ({e.code}). Keyinroq urinib ko'ring."
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Internetga ulanib bo'lmadi. Tarmoqni tekshirib, qayta urinib ko'ring."
    if isinstance(e, FileNotFoundError):
        return f"Fayl yoki papka topilmadi: {e.filename}"
    if isinstance(e, PermissionError):
        return f"Ruxsat yo'q: {e.filename}"
    return str(e) or e.__class__.__name__


def version_tuple(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("vV")
    out = []
    for part in v.split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def data_dir() -> str:
    """Foydalanuvchi ma'lumotlari papkasi (yangilanishlar shu yerga yuklanadi)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MyOwnRobot")


def updates_dir() -> str:
    return os.environ.get("MYOWNROBOT_UPDATES_DIR") or os.path.join(data_dir(), "updates")


def bundled_manifest() -> dict | None:
    """Ishlab turgan dastur paketi bilan kelgan manifest (manba koddan ishlaganda - None)."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    path = os.path.join(base, "app", "manifest.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ------------------------------------------------------------------ manbalar

@dataclass
class UpdateInfo:
    manifest: dict
    source: "Source"

    @property
    def version(self) -> str:
        return self.manifest["version"]

    @property
    def notes(self) -> str:
        return self.manifest.get("notes", "")

    def needs_full(self, libs: str | None) -> bool:
        """Kutubxonalar farq qiladimi (to'liq yangilanish kerak)."""
        return libs is not None and self.manifest.get("libs") != libs


class Source:
    def manifest(self) -> dict:
        raise NotImplementedError

    def download(self, name: str, dest: str, progress=None) -> None:
        raise NotImplementedError


class FolderSource(Source):
    """Tarmoq yoki mahalliy papka: update.json va zip fayllar shu papkada."""

    def __init__(self, folder: str):
        self.folder = folder

    def manifest(self) -> dict:
        with open(os.path.join(self.folder, MANIFEST_NAME), encoding="utf-8") as f:
            return json.load(f)

    def download(self, name: str, dest: str, progress=None) -> None:
        src = os.path.join(self.folder, os.path.basename(name))
        total = os.path.getsize(src)
        done = 0
        with open(src, "rb") as fi, open(dest, "wb") as fo:
            while chunk := fi.read(1 << 20):
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub fayllarni boshqa serverga (objects.githubusercontent.com) yo'naltiradi. U yerga token
    yuborilmasligi kerak - aks holda server so'rovni rad etadi."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for h in ("Authorization", "authorization"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


_opener = urllib.request.build_opener(_DropAuthOnRedirect)

def normalize_repo(text: str) -> str:
    """Repozitoriy maydonini "egasi/nomi" ko'rinishiga keltiradi.

    Qabul qilinadi: "egasi/nomi", "https://github.com/egasi/nomi", "github.com/egasi/nomi.git",
    "git@github.com:egasi/nomi.git", oxiridagi "/" yoki "/releases..." qismlari. Tushunib bo'lmasa -
    standart repozitoriy.
    """
    t = (text or "").strip().strip('"').strip("'").strip()
    t = re.sub(r"^(git@github\.com:|(https?://)?(www\.)?github\.com/)", "", t, flags=re.I)
    parts = [p for p in t.split("/") if p]
    if len(parts) < 2:
        return DEFAULT_REPO
    owner, name = parts[0], parts[1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner) or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return DEFAULT_REPO
    return f"{owner}/{name}"


TOKEN_HELP = ("GitHub → Settings → Developer settings → Fine-grained tokens → yangi token: "
              "Repository access - shu repozitoriy, Permissions - Contents: Read-only.")


class GitHubSource(Source):
    """GitHub Releases: oxirgi reliz. Yopiq repo uchun faqat o'qish huquqli token kerak."""

    def __init__(self, repo: str = DEFAULT_REPO, token: str = ""):
        self.repo = normalize_repo(repo)
        self.token = token.strip().strip('"').strip("'")
        self._assets: dict[str, str] | None = None

    def _request(self, url: str, accept: str = "application/vnd.github+json", token: str | None = None):
        token = self.token if token is None else token
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "MyOwnRobot"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        return _opener.open(req, timeout=30)

    def _explain(self, e: urllib.error.HTTPError) -> UpdateError:
        """GitHub javobini aniq, foydalanuvchi tushunadigan sababga aylantiradi (manzil bilan)."""
        err = self._explain_text(e)
        url = (getattr(e, "url", None) or getattr(e, "filename", None) or "").split("?")[0]
        return UpdateError(f"{err}\nManzil: {url}" if url else str(err))

    def _explain_text(self, e: urllib.error.HTTPError) -> UpdateError:
        code = e.code
        remaining = (e.headers or {}).get("X-RateLimit-Remaining") if e.headers else None
        if code == 403 and remaining == "0":
            return UpdateError("GitHub so'rovlar chegarasi tugadi (403). Bir soatdan keyin urinib ko'ring "
                               "yoki token kiriting.")
        if code == 401:
            return UpdateError("Token noto'g'ri yoki muddati o'tgan (GitHub 401). Yangilanish sozlamalarida "
                               "yangi token kiriting. " + TOKEN_HELP)
        if code == 403:
            return UpdateError("Tokenga bu repozitoriyni o'qish ruxsati berilmagan (GitHub 403). " + TOKEN_HELP)
        if code == 404:
            if self.token:
                return UpdateError(f"Token \"{self.repo}\" repozitoriyini ko'ra olmaydi yoki reliz yo'q "
                                   "(GitHub 404). " + TOKEN_HELP)
            return UpdateError(f"\"{self.repo}\" da hali yangilanish relizi yo'q (GitHub 404). Reliz `main` ga versiya "
                               "oshirilgan birlashtirishdan keyin avtomatik chiqadi. Repozitoriy nomini tekshiring "
                               "(egasi/nomi); yopiq repozitoriy bo'lsa token kiriting.")
        return UpdateError(f"GitHub xatosi ({code}). Keyinroq urinib ko'ring.")

    def _asset_urls(self) -> dict[str, str]:
        if self._assets is None:
            with self._request(f"https://api.github.com/repos/{self.repo}/releases/latest") as r:
                rel = json.load(r)
            self._assets = {a["name"]: a["url"] for a in rel.get("assets", [])}
        return self._assets

    def _open(self, name: str):
        public = f"https://github.com/{self.repo}/releases/latest/download/{name}"
        try:
            if not self.token:
                return self._request(public, "application/octet-stream")
            try:
                url = self._asset_urls().get(name)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    # token yaroqsiz - repozitoriy ochiq bo'lsa tokensiz ham ishlaydi
                    try:
                        return self._request(public, "application/octet-stream", token="")
                    except urllib.error.HTTPError:
                        pass
                raise
            if not url:
                raise UpdateError(f"Oxirgi relizda fayl topilmadi: {name}")
            return self._request(url, "application/octet-stream")
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise           # server vaqtincha ishlamayapti - qayta urinish mumkin
            raise self._explain(e) from e

    def manifest(self) -> dict:
        with self._open(MANIFEST_NAME) as r:
            return json.load(r)

    def download(self, name: str, dest: str, progress=None) -> None:
        with self._open(name) as r, open(dest, "wb") as fo:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)


def make_source(settings: dict) -> Source:
    """settings: {"kind": "github"|"folder", "folder": ..., "repo": ..., "token": ...}"""
    if settings.get("kind") == "folder":
        folder = settings.get("folder", "")
        if not folder:
            raise UpdateError("Yangilanishlar papkasi ko'rsatilmagan (Yangilanish sozlamalari)")
        return FolderSource(folder)
    return GitHubSource(settings.get("repo") or DEFAULT_REPO, settings.get("token", ""))


# ------------------------------------------------------------------ tekshirish va o'rnatish

def current_version() -> str:
    return __version__


def check(source: Source, current: str | None = None) -> UpdateInfo | None:
    """Yangi versiya bo'lsa - UpdateInfo, aks holda None."""
    m = source.manifest()
    if not isinstance(m, dict) or "version" not in m:
        raise UpdateError("update.json noto'g'ri")
    if version_tuple(m["version"]) > version_tuple(current or current_version()):
        return UpdateInfo(m, source)
    return None


def downloaded(version: str) -> dict | None:
    """Shu versiya allaqachon yuklab olinganmi (qayta ochishni kutmoqda): uning manifesti yoki None."""
    d = os.path.join(updates_dir(), version)
    try:
        if os.path.exists(os.path.join(d, "BROKEN")) or not os.path.exists(os.path.join(d, APP_ZIP_NAME)):
            return None
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_broken(version: str) -> bool:
    """Bu versiya avval yuklangan, lekin ishga tushmagan (desktop_app.py BROKEN belgisini qo'ygan)."""
    return os.path.exists(os.path.join(updates_dir(), version, "BROKEN"))


def installed_notes(version: str) -> str:
    """Yuklab o'rnatilgan versiyaning "nima yangi" matni (bo'lmasa - bo'sh)."""
    m = downloaded(version)
    if m is None:
        b = bundled_manifest() or {}
        m = b if b.get("version") == version else {}
    return m.get("notes", "")


def _download_retry(source: Source, name: str, dest: str, progress=None, attempts: int = RETRIES) -> None:
    """Yuklash; tarmoq uzilsa bir necha marta qayta urinadi (2, 4 ... soniya kutib)."""
    for i in range(attempts):
        try:
            source.download(name, dest, progress)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if isinstance(e, (FileNotFoundError, PermissionError)) or \
                    (isinstance(e, urllib.error.HTTPError) and e.code < 500):
                raise
            if i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _verify(path: str, expected: str | None) -> None:
    if expected and _sha256(path).lower() != expected.lower():
        raise UpdateError("Yuklangan fayl buzilgan (SHA-256 mos kelmadi). Qayta urinib ko'ring.")


def install_code_update(info: UpdateInfo, progress=None) -> str:
    """Kod yangilanishini yuklaydi. Natija dastur qayta ochilganda kuchga kiradi."""
    m = info.manifest
    target = os.path.join(updates_dir(), m["version"])
    os.makedirs(updates_dir(), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="mor_upd_", dir=updates_dir())
    try:
        zpath = os.path.join(tmp, APP_ZIP_NAME)
        _download_retry(info.source, m["app_zip"], zpath, progress)
        _verify(zpath, m.get("app_sha256"))
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None or "sl_desktop/__init__.py" not in z.namelist():
                raise UpdateError("Yangilanish arxivi noto'g'ri")
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"version": m["version"], "libs": m.get("libs"), "notes": m.get("notes", "")}, f,
                      ensure_ascii=False)
        if os.path.exists(target):
            shutil.rmtree(target)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
    cleanup_old(keep=m["version"])
    return target


def cleanup_old(keep: str) -> None:
    """Eski kod yangilanishlarini o'chiradi (oxirgisi va ishlayotgani qoladi)."""
    d = updates_dir()
    if not os.path.isdir(d):
        return
    running = os.environ.get("MYOWNROBOT_RUNNING_VERSION")
    for name in os.listdir(d):
        if name not in (keep, running) and os.path.isdir(os.path.join(d, name)):
            shutil.rmtree(os.path.join(d, name), ignore_errors=True)


def _ps(text: str) -> str:
    """PowerShell satri: bitta tirnoq ichida, apostroflar ikkilanadi ("O'quv" kabi nomlar uchun)."""
    return "'" + text.replace("'", "''") + "'"


def install_dir() -> str:
    """Dastur papkasi (MyOwnRobot.exe joylashgan)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def prepare_full_update(info: UpdateInfo, progress=None) -> str:
    """To'liq paketni yuklaydi va almashtiruvchi PowerShell skriptini tayyorlaydi (yo'lini qaytaradi).

    Skript dastur yopilishini kutadi, papkani yangisi bilan almashtiradi va dasturni qayta ochadi.
    """
    if os.name != "nt" or not is_frozen():
        raise UpdateError("To'liq yangilanish faqat Windows'dagi o'rnatilgan dasturda ishlaydi")
    m = info.manifest
    work = tempfile.mkdtemp(prefix="mor_full_")
    zpath = os.path.join(work, "full.zip")
    if not m.get("full_zip"):
        raise UpdateError("Bu relizda to'liq paket yo'q")
    _download_retry(info.source, m["full_zip"], zpath, progress)
    _verify(zpath, m.get("full_sha256"))
    with zipfile.ZipFile(zpath) as z:
        if not any(n.lower().endswith("myownrobot.exe") for n in z.namelist()):
            raise UpdateError("To'liq paket noto'g'ri: MyOwnRobot.exe topilmadi")
    target = install_dir()
    exe = sys.executable
    script = os.path.join(work, "update.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(f"""$ErrorActionPreference = 'Stop'
$pidToWait = {os.getpid()}
$zip = {_ps(zpath)}
$work = {_ps(work)}
$target = {_ps(target)}
$exe = {_ps(exe)}
try {{ Wait-Process -Id $pidToWait -Timeout 120 -ErrorAction SilentlyContinue }} catch {{}}
Expand-Archive -Path $zip -DestinationPath (Join-Path $work 'new') -Force
$src = Get-ChildItem (Join-Path $work 'new') -Directory | Select-Object -First 1
$backup = $target + '.old'
if (Test-Path $backup) {{ Remove-Item $backup -Recurse -Force }}
try {{
    Copy-Item $target $backup -Recurse -Force
    Get-ChildItem $src.FullName | Copy-Item -Destination $target -Recurse -Force
    Remove-Item $backup -Recurse -Force
}} catch {{
    if (Test-Path $backup) {{ Copy-Item (Join-Path $backup '*') $target -Recurse -Force }}
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Yangilab bo'lmadi: $($_.Exception.Message)", 'MyOwnRobot') | Out-Null
}}
Start-Process -FilePath $exe
""")
    return script


def launch_full_update(script: str) -> None:
    """Skriptni alohida jarayonda ishga tushiradi (keyin dastur yopilishi kerak)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", script], creationflags=flags, close_fds=True)
