# Spotify na Barra

Mini player que aparece na barra de tarefas do Windows quando o Spotify começa a tocar. Clique para abrir o painel
completo: capa, progresso, letra sincronizada (LRCLIB), volume, saída de áudio e timer.
Controla o Spotify pelos controles de mídia do Windows (SMTC) — não precisa de API do Spotify.

## Instalar e rodar
1. Python 3.10+.
2. `instalar.bat` (cria a `.venv` e instala o `requirements.txt`).
3. `iniciar.bat`.

Sem Windows (ou com `SB_DEMO=1`) abre em modo demonstração.

## Gerar o .exe
`gerar_exe.bat` → `dist\SpotifyNaBarra.exe`.

Uso, limitações e solução de problemas: `LEIA-ME.txt`. Log em `%APPDATA%\SpotifyNaBarra\log.txt`.

## Versão atual
**1.0.0**. O número fica em `APP_VERSAO` no código e aparece no título da janela e no log. Para gerar o `.exe`, rode `gerar_exe.ps1`: ele grava a versão nas propriedades do arquivo e recusa repetir um número já usado.
