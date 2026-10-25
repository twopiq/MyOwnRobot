"""Foydalanuvchi ma'lumotlari joyi: baza, sozlamalar, modellar (ilova papkasidan tashqarida — yangilanishda saqlanadi)."""
import os
from pathlib import Path


def user_dir() -> Path:
    env = os.environ.get("MYOWNROBOT_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MyOwnRobot"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "MyOwnRobot"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return user_dir() / "robot.db"


def models_dir() -> Path:
    p = user_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p
