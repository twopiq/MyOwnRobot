@echo off
rem MyOwnRobot desktop ilovasi (birinchi marta: python -m venv .venv_bot && .venv_bot\Scripts\pip install -r requirements.txt)
cd /d "%~dp0"
if exist .venv_bot\Scripts\pythonw.exe (
  start "" .venv_bot\Scripts\pythonw.exe desktop_app.py
) else (
  start "" pythonw desktop_app.py
)
