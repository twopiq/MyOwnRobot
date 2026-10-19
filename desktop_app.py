"""MyOwnRobot desktop ilovasi.

    python desktop_app.py                 — ilovani ochish
    python desktop_app.py --robot [...]   — robotning o'zi (selflearn_robot.py argumentlari; .exe ichida ishlatiladi)
    python desktop_app.py --self-test out.json   — oynani yaratib tekshiradi (CI uchun)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--robot":
        sys.argv = ["selflearn_robot.py"] + sys.argv[2:]
        import selflearn_robot
        selflearn_robot.main()
        return 0
    from PySide6.QtWidgets import QApplication
    from sl_desktop import __version__
    from sl_desktop.app import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("MyOwnRobot")
    w = MainWindow()
    if len(sys.argv) > 2 and sys.argv[1] == "--self-test":
        for k in w.pages:
            w.go(k)
        Path(sys.argv[2]).write_text(json.dumps({"version": __version__, "pages": list(w.pages)}), encoding="utf-8")
        return 0
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
