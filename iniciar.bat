@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0spotify_barra.py"
) else (
  start "" pythonw "%~dp0spotify_barra.py"
)
