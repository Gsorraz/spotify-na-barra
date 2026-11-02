@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
%PY% -m pip install pyinstaller
if errorlevel 1 (
  echo ERRO ao instalar o PyInstaller. Rode o instalar.bat primeiro.
  pause
  exit /b 1
)
%PY% -m PyInstaller --noconfirm --onefile --windowed --name SpotifyNaBarra --icon icone.ico --collect-all winrt --hidden-import comtypes.stream --hidden-import pycaw.pycaw spotify_barra.py
if errorlevel 1 (
  echo ERRO ao gerar o executavel.
  pause
  exit /b 1
)
echo.
echo Executavel gerado em: %~dp0dist\SpotifyNaBarra.exe
pause
