@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando dependencias do Spotify na Barra...

rem Procura um Python 3.10+ (o "python" do PATH pode ser antigo demais).
set "PYCMD="
for %%V in (3.13 3.12 3.11 3.10 3.14) do (
  if not defined PYCMD (
    py -%%V -c "import sys" >nul 2>&1 && set "PYCMD=py -%%V"
  )
)
if not defined PYCMD (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
  echo.
  echo ERRO: nao encontrei Python 3.10 ou mais novo. Instale em python.org
  echo       marcando "Add to PATH" e rode este arquivo de novo.
  pause
  exit /b 1
)
echo Usando: %PYCMD%

rem Ambiente isolado na pasta do programa (nao mexe no Python do sistema).
if not exist ".venv\Scripts\python.exe" (
  %PYCMD% -m venv .venv
  if errorlevel 1 goto erro
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro
echo.
echo Pronto! Agora rode o iniciar.bat
pause
exit /b 0

:erro
echo.
echo ERRO na instalacao. Veja as mensagens acima (internet ativa? Python 3.10+?).
pause
exit /b 1
