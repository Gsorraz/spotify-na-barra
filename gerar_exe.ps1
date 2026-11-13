# Gera SpotifyNaBarra.exe (PyInstaller --onefile --windowed) com o número de APP_VERSAO nas propriedades.
# Uso:  powershell -File gerar_exe.ps1            -> gera em %TEMP% e põe o .exe em dist\
#       powershell -File gerar_exe.ps1 -SemTrocar -> só gera em %TEMP%\build_spotify\dist
# Antes: rodar os testes e fechar o app se estiver aberto. Não encerra nenhum processo.
param([switch]$SemTrocar)
$ErrorActionPreference = 'Stop'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$fonte = Join-Path $pasta 'spotify_barra.py'
$m = Select-String -Path $fonte -Pattern '^APP_VERSAO\s*=\s*"(\d+)\.(\d+)\.(\d+)"' | Select-Object -First 1
if (-not $m) { throw 'APP_VERSAO (formato "1.0.0") nao encontrada em spotify_barra.py' }
$v = $m.Matches[0].Groups; $maj = [int]$v[1].Value; $min = [int]$v[2].Value; $pat = [int]$v[3].Value
$versao = "$maj.$min.$pat"

# nao gerar dois .exe com o mesmo numero
$ultima = Join-Path $pasta 'testes\logs\ultima_versao_exe.txt'
if (Test-Path $ultima) {
    $anterior = (Get-Content $ultima -Raw).Trim()
    if ($anterior -eq $versao) { throw "A versao $versao ja foi gerada. Aumente APP_VERSAO em spotify_barra.py antes de gerar o .exe." }
}

$py = Join-Path $pasta '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
& $py -m pip install --quiet pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'falha ao instalar o PyInstaller (rode o instalar.bat antes)' }

$w = Join-Path $env:TEMP 'build_spotify'
if (Test-Path $w) { Remove-Item $w -Recurse -Force }
New-Item -ItemType Directory $w | Out-Null
$vi = Join-Path $w 'versao.txt'
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($maj, $min, $pat, 0), prodvers=($maj, $min, $pat, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'Gian'),
      StringStruct('FileDescription', 'Spotify na Barra'),
      StringStruct('FileVersion', '$versao'),
      StringStruct('InternalName', 'SpotifyNaBarra'),
      StringStruct('OriginalFilename', 'SpotifyNaBarra.exe'),
      StringStruct('ProductName', 'Spotify na Barra'),
      StringStruct('ProductVersion', '$versao')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
"@ | Set-Content -Path $vi -Encoding UTF8

$ico = Join-Path $pasta 'icone.ico'
& $py -m PyInstaller --noconfirm --onefile --windowed --icon $ico --version-file $vi --name SpotifyNaBarra `
    --collect-all winrt --hidden-import comtypes.stream --hidden-import pycaw.pycaw `
    --distpath (Join-Path $w 'dist') --workpath (Join-Path $w 'work') --specpath $w $fonte
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou ($LASTEXITCODE)" }
$novo = Join-Path $w 'dist\SpotifyNaBarra.exe'
if (-not (Test-Path $novo)) { throw 'o .exe nao foi gerado' }
$pv = (Get-Item $novo).VersionInfo.ProductVersion
if ($pv -ne $versao) { throw "versao nas propriedades ($pv) difere de APP_VERSAO ($versao)" }

if ($SemTrocar) { Write-Host "Gerado (sem trocar): $novo  v$versao"; exit 0 }
$dist = Join-Path $pasta 'dist'
New-Item -ItemType Directory $dist -Force | Out-Null
$destino = Join-Path $dist 'SpotifyNaBarra.exe'
Remove-Item $destino -Force -ErrorAction SilentlyContinue
if (Test-Path $destino) { throw "nao consegui apagar $destino (o app esta aberto?)" }
Copy-Item $novo $destino
Set-Content -Path $ultima -Value $versao -Encoding ASCII
Write-Host "OK: SpotifyNaBarra.exe v$versao em $dist"
