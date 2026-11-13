# Testes do modo "ocioso" (Spotify de desktop aberto sem sessao de midia) em spotify_barra.py.
# Sem Spotify real, sem tecla de midia real (keybd_event falso), sem navegador, APPDATA temporario.
# Leitura de processos/janelas e somente leitura: nao cria janela nem processo.
# Uso: python teste_idle_spotify.py "<motivo>"
import os, sys, time, json, tempfile, hashlib, subprocess, datetime, types, ctypes, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SB_DEMO"] = "1"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="sb_idle_")
PASTA = os.path.dirname(os.path.abspath(__file__))
SPOT = os.path.dirname(PASTA)
sys.path.insert(0, SPOT)
import spotify_barra as sb
from ctypes import wintypes
from PySide6.QtWidgets import QApplication

MOTIVO = sys.argv[1] if len(sys.argv) > 1 else "modo ocioso do Spotify"
REAL = sys.stdout
RES, LINHAS = [], []


def out(s):
    LINHAS.append(s)
    REAL.write(s + "\n")
    REAL.flush()


def chk(cond, desc):
    RES.append(bool(cond))
    out(("  ok    " if cond else "FALHA ") + desc)


def nao_verificado(desc):
    out("  NAO VERIF " + desc)


class DemoOff:
    def __enter__(self):
        self.v = sb.DEMO
        sb.DEMO = False

    def __exit__(self, *a):
        sb.DEMO = self.v


def nomes_processos():
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace")
    return {l.split(",")[0].strip('"').lower() for l in r.stdout.splitlines() if l.strip()}


def real(playing, key="k1", app="Spotify.exe"):
    return {"app": app, "title": "Faixa", "artist": "Art", "album": "Alb", "playing": playing,
            "position": 10.0, "duration": 200.0, "shuffle": False, "repeat": "off",
            "key": key, "_t": time.monotonic()}


k32 = ctypes.windll.kernel32
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


def handles():
    c = wintypes.DWORD()
    k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(c))
    return c.value


def bloco(nome, fn):
    out(f"\n== {nome}")
    try:
        fn()
    except Exception:
        RES.append(False)
        out("FALHA excecao em " + nome + ":\n" + traceback.format_exc())


# ---------- A. spotify_window_open() (leitura real de processos e janelas)
def bloco_a():
    chk(sb.SPOTIFY_EXE == "spotify.exe", "constante SPOTIFY_EXE == 'spotify.exe'")
    with DemoOff():
        sb.SPOTIFY_EXE = "nao_existe_xyz_123.exe"
        chk(sb.spotify_window_open() is False, "processo inexistente -> False")
        nomes = nomes_processos()
        alvo = next((c for c in ["chrome.exe", "msedge.exe", "claude.exe", "notepad.exe", "explorer.exe"]
                     if c in nomes), None)
        if alvo:
            sb.SPOTIFY_EXE = alvo
            chk(sb.spotify_window_open() is True, f"processo com janela real ({alvo}) -> True")
        else:
            nao_verificado("nenhum processo de teste (chrome/edge/claude/notepad/explorer) rodando")
        sb.SPOTIFY_EXE = "nao_existe_xyz_123.exe"
        h0, t0 = handles(), time.perf_counter()
        for _ in range(300):
            sb.spotify_window_open()
        dt = (time.perf_counter() - t0) / 300
        h1 = handles()
        chk(h1 - h0 <= 2, f"300 chamadas (sem processo) nao vazam handle (delta {h1 - h0})")
        chk(dt < 0.05, f"custo por chamada {dt * 1000:.2f} ms (limite 50 ms; roda a cada 2,5 s)")
        if alvo:
            sb.SPOTIFY_EXE = alvo
            h0 = handles()
            for _ in range(300):
                sb.spotify_window_open()
            h1 = handles()
            chk(h1 - h0 <= 2, f"300 chamadas (com janela de {alvo}) nao vazam handle (delta {h1 - h0})")
        sb.SPOTIFY_EXE = "spotify.exe"
    chk(ctypes.sizeof(ctypes.c_void_p) == 8, "processo de 64 bits (HANDLE = 8 bytes)")


# ---------- B. Controller: transicoes, visibilidade, comandos e letra no modo ocioso
def bloco_b():
    app = QApplication.instance() or QApplication([])
    JAN = {"on": False, "n": 0}

    def janela():
        JAN["n"] += 1
        return JAN["on"]

    sb.spotify_window_open = janela
    ctl = sb.Controller()
    try:
        ctl.worker.state.disconnect(ctl._on_state)   # so o worker demo nao interfere
    except Exception:
        pass
    CMDS = []
    ctl.worker.cmd = lambda *a, **k: CMDS.append(a[0])
    ctl.cfg["hide_on_pause"] = False
    ctl.cfg["other_players"] = False

    def abre_fecha(on):
        JAN["on"] = on
        ctl._idle_check_t = 0.0

    abre_fecha(False)
    ctl._on_state(None)
    chk(ctl.st is None and not ctl.mini.isVisible(), "Spotify fechado, sem sessao -> barra escondida")

    abre_fecha(True)
    ctl._on_state(None)
    chk(ctl.st and ctl.st.get("idle") and ctl.st["app"] == "Spotify.exe",
        "Spotify aberto sem sessao -> estado ocioso sintetico")
    chk(ctl.mini.isVisible(), "ocioso -> mini player aparece ANTES do primeiro play")

    n0 = JAN["n"]
    for _ in range(50):
        ctl._on_state(None)
    chk(JAN["n"] == n0, "50 atualizacoes seguidas dentro de 2,5 s nao varrem janelas de novo (throttle)")

    ctl._on_state(real(False))
    chk(ctl.st and not ctl.st.get("idle"), "sessao real pausada substitui o ocioso")
    chk(ctl.mini.isVisible(), "sessao real pausada do Spotify -> visivel (app contem 'spotify')")

    ctl._on_state(real(True))
    chk(ctl.ever_played and ctl.mini.isVisible(), "sessao real tocando -> ever_played e visivel")

    ctl._on_state(None)   # sessao some, janela ainda aberta
    chk(ctl.st and ctl.st.get("idle") and ctl.mini.isVisible(), "sessao some com Spotify aberto -> volta ocioso e visivel")
    chk(ctl.ever_played is True, "ocioso mantem ever_played (inofensivo: app Spotify ja mostra a barra)")

    abre_fecha(False)
    ctl._on_state(None)
    chk(ctl.st is None and ctl.ever_played is False and not ctl.mini.isVisible(), "Spotify fechado -> ocioso some, ever_played zera, barra escondida")

    # hide_on_pause com ocioso
    ctl.cfg["hide_on_pause"] = True
    abre_fecha(True)
    ctl._on_state(None)
    chk(ctl.st and ctl.st.get("idle") and not ctl.mini.isVisible(),
        "hide_on_pause ligado + ocioso (nao toca) -> escondido")
    ctl._on_state(real(True))
    chk(ctl.mini.isVisible(), "hide_on_pause ligado + sessao tocando -> visivel")
    ctl._on_state(real(False))
    chk(not ctl.mini.isVisible(), "hide_on_pause ligado + sessao pausada -> escondido")
    ctl.cfg["hide_on_pause"] = False

    # fluxo sem ocioso (sessao real de outros apps)
    ctl._on_state(None)
    abre_fecha(False)
    ctl._on_state(None)
    ctl.ever_played = False
    ctl._on_state(real(False, key="c1", app="chrome.exe"))
    chk(not ctl.mini.isVisible(), "app nao-Spotify pausado, nunca tocou -> escondido (igual antes)")
    ctl._on_state(real(True, key="c2", app="chrome.exe"))
    chk(ctl.mini.isVisible(), "app nao-Spotify tocando -> visivel (igual antes)")
    ctl._on_state(None)
    chk(not ctl.mini.isVisible(), "sem sessao e sem Spotify -> escondido")

    # comandos no ocioso: teclas de midia, nunca o worker
    fu = types.SimpleNamespace(calls=[])
    fu.keybd_event = lambda vk, sc, fl, ex: fu.calls.append((vk, fl))
    real_ct, real_is_win = sb.ctypes, sb.IS_WIN
    try:
        sb.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=fu))
        sb.IS_WIN = True
        abre_fecha(True)
        ctl._on_state(None)
        CMDS.clear()
        ctl.cmd("playpause")
        chk(fu.calls == [(0xB3, 0), (0xB3, 2)], f"ocioso: playpause = tecla 0xB3 (down+up) {fu.calls}")
        fu.calls.clear()
        ctl.cmd("next"); ctl.cmd("prev")
        chk(fu.calls == [(0xB0, 0), (0xB0, 2), (0xB1, 0), (0xB1, 2)], "ocioso: next/prev = 0xB0/0xB1")
        chk(CMDS == [], "ocioso: nenhum comando foi para o worker")
        ctl._on_state(real(True))
        fu.calls.clear()
        ctl.cmd("playpause")
        chk(CMDS == ["playpause"] and fu.calls == [], "sessao real: comando vai ao worker, sem tecla de midia")
    finally:
        sb.ctypes, sb.IS_WIN = real_ct, real_is_win

    # letra no ocioso
    chamadas = []
    sb.fetch_lyrics = lambda *a, **k: chamadas.append(a) or {"error": True}
    ctl._on_state(None)
    abre_fecha(True)
    ctl._on_state(None)
    ctl.lyrics_key = None
    ctl.ensure_lyrics()
    chk(chamadas == [] and ctl.lyrics_key is None, "ocioso: ensure_lyrics mostra mensagem e nao busca letra")

    # _pick do worker (other_players)
    Wk = next(v for v in vars(sb).values() if isinstance(v, type) and "_pick" in vars(v))

    class Mgr:
        def __init__(self, apps, cur):
            self.apps, self.cur = apps, cur

        def get_sessions(self):
            return [types.SimpleNamespace(source_app_user_model_id=a) for a in self.apps]

        def get_current_session(self):
            return self.cur

    cfg = {"other_players": False}
    me = types.SimpleNamespace(cfg=cfg)
    sess_chrome = types.SimpleNamespace(source_app_user_model_id="chrome.exe")
    sess_sp = types.SimpleNamespace(source_app_user_model_id="Spotify.exe")
    chk(Wk._pick(me, Mgr(["chrome.exe"], sess_chrome)) is None, "other_players OFF: so chrome -> ignorado")
    cfg["other_players"] = True
    chk(Wk._pick(me, Mgr(["chrome.exe"], sess_chrome)) is sess_chrome, "other_players ON: sessao atual de outro app")
    chk(getattr(Wk._pick(me, Mgr(["chrome.exe", "Spotify.exe"], sess_chrome)), "source_app_user_model_id", None) == "Spotify.exe", "_pick com Spotify presente -> prioriza Spotify")
    cfg["other_players"] = False
    chk(getattr(Wk._pick(me, Mgr(["Spotify.exe"], sess_sp)), "source_app_user_model_id", None) == "Spotify.exe", "Spotify como sessao de midia sempre escolhido")
    ctl.deleteLater() if hasattr(ctl, "deleteLater") else None
    sb.spotify_window_open = lambda: False


def main():
    sb.DEMO = True
    bloco("A. spotify_window_open (leitura real)", bloco_a)
    bloco("B. Controller: idle, visibilidade, comandos, letra, other_players", bloco_b)
    ok, falhas = sum(RES), len(RES) - sum(RES)
    out(f"\nRESULTADO: {ok} ok, {falhas} falhas")
    versao = hashlib.sha1(open(os.path.join(SPOT, "spotify_barra.py"), "rb").read()).hexdigest()[:10]
    logs = os.path.join(PASTA, "logs")
    os.makedirs(logs, exist_ok=True)
    reg = {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "versao": versao,
           "suite": "idle_spotify", "ok": ok, "falhas": falhas, "motivo": MOTIVO}
    with open(os.path.join(logs, "execucoes.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    with open(os.path.join(logs, "ultima_saida_idle_spotify.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LINHAS) + "\n")
    sys.exit(0 if falhas == 0 and RES else 1)


if __name__ == "__main__":
    main()
