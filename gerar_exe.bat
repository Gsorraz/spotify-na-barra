@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gerar_exe.ps1"
if errorlevel 1 (
  echo ERRO ao gerar o executavel.
  pause
  exit /b 1
)
pause
