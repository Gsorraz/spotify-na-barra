# Testes de borda da API Web do Spotify (spotify_barra.py).
# Sem janela, sem navegador (webbrowser.open trocado), sem rede real: servidor falso em 127.0.0.1 (porta efemera).
# APPDATA temporario: nunca toca nos dados reais. Uso: python teste_bordas_api.py "<motivo>"
import os, sys, json, time, threading, tempfile, io, re, hashlib, contextlib, datetime
import urllib.parse as up
import urllib.request as ur
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SB_DEMO"] = "1"
TMP = tempfile.mkdtemp(prefix="sb_bordas_")
os.environ["APPDATA"] = TMP
PASTA = os.path.dirname(os.path.abspath(__file__))
SPOT = os.path.dirname(PASTA)
sys.path.insert(0, SPOT)
import webbrowser
import spotify_barra as sb
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOTIVO = sys.argv[1] if len(sys.argv) > 1 else "bordas da API"
REAL = sys.stdout
RES, LINHAS = [], []


def out(s):
    LINHAS.append(s)
    REAL.write(s + "\n")
    REAL.flush()


def chk(cond, desc):
    RES.append(bool(cond))
    out(("  ok    " if cond else "FALHA ") + desc)


PLAYER_OK = {"device": {"name": "PC", "type": "Computer", "volume_percent": 40, "supports_volume": True},
             "shuffle_state": False, "repeat_state": "off", "is_playing": True,
             "item": {"id": "T1", "type": "track", "name": "Faixa 1", "artists": [{"name": "Art"}]}}
S = {}


def reset():
    S.update({"token": "ok", "n_tok": 0, "n401": 0, "libput": 204, "tracksput": 204,
              "player": (200, PLAYER_OK), "queue": (200, {"queue": []}),
              "lib": (200, [False]), "tracks": (200, [False])})
    S["hits"] = []
    S["vol"] = []
    S["lock"] = threading.Lock()


reset()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, hdr=None):
        b = obj if isinstance(obj, bytes) else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_response(code)
        for k, v in (hdr or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if b:
            self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _rota(self, m):
        body = self._body()
        p = self.path
        path = p.split("?")[0]
        with S["lock"]:
            S["hits"].append((m, path, self.headers.get("Authorization")))
        if path == "/api/token":
            with S["lock"]:
                S["n_tok"] += 1
                n = S["n_tok"]
            modo = S["token"]
            if modo == "invalid":
                return self._send(400, {"error": "invalid_grant"})
            if modo == "500":
                return self._send(500, {"error": "server_error"})
            if modo == "html":
                return self._send(200, b"<html>oops</html>")
            return self._send(200, {"access_token": f"AT{n}", "refresh_token": "RT2", "expires_in": 3600})
        if self.headers.get("Authorization") is None:
            return self._send(401, {"error": "sem token"})
        with S["lock"]:
            if S["n401"] > 0:
                S["n401"] -= 1
                return self._send(401, {"error": {"status": 401}})
        if path == "/v1/teste/500":
            return self._send(500, {"error": "x"})
        if path == "/v1/teste/403":
            return self._send(403, {"error": {"status": 403, "message": "Premium required"}})
        if path == "/v1/teste/429":
            return self._send(429, {"error": "rate"}, hdr={"Retry-After": "abc"})
        if path == "/v1/teste/html":
            return self._send(200, b"<html>")
        if path == "/v1/teste/204":
            return self._send(204)
        if path == "/v1/me/player/queue":
            return self._send(*S["queue"])
        if path == "/v1/me/player/volume":
            with S["lock"]:
                S["vol"].append(int(up.parse_qs(up.urlparse(p).query)["volume_percent"][0]))
            return self._send(204)
        if path in ("/v1/me/player/shuffle", "/v1/me/player/repeat"):
            return self._send(204)
        if path == "/v1/me/player":
            return self._send(*S["player"])
        if path == "/v1/me/library/contains":
            return self._send(*S["lib"])
        if path == "/v1/me/library":
            return self._send(S["libput"], None)
        if path == "/v1/me/tracks/contains":
            return self._send(*S["tracks"])
        if path == "/v1/me/tracks":
            return self._send(S["tracksput"], None)
        if path == "/v1/me":
            return self._send(200, {"display_name": "Teste", "product": "premium"})
        return self._send(404, {"error": "nao existe"})

    def do_GET(self):
        self._rota("GET")

    def do_POST(self):
        self._rota("POST")

    def do_PUT(self):
        self._rota("PUT")

    def do_DELETE(self):
        self._rota("DELETE")


SRV = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{SRV.server_address[1]}"
CONTA = [0]


def novo_web(conectado=True, expira_em=3600, api=None):
    CONTA[0] += 1
    w = sb.SpotifyWeb(os.path.join(TMP, f"spotify_{CONTA[0]}.json"))
    w.TOKEN_URL = BASE + "/api/token"
    w.API_URL = api or (BASE + "/v1")
    if conectado:
        with w._lock:
            w._d = {"client_id": "cid_teste", "access_token": "AT0", "refresh_token": "RT1",
                    "expires_at": time.time() + expira_em, "product": "premium", "name": "Teste"}
            w._save()
    return w


class Emit:
    def __init__(self):
        self.ev, self.lk = [], threading.Lock()

    def __call__(self, tipo, dado):
        with self.lk:
            self.ev.append((tipo, dado))

    def tipos(self, t):
        with self.lk:
            return [d for x, d in self.ev if x == t]


def esperar(cond, t=4.0):
    fim = time.time() + t
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


def poller(w, panel=False, on=True, fila=False):
    em = Emit()
    p = sb.SpotifyPoller(w, em)
    p.start()
    p.set_flags(panel_open=panel, spotify_on=on, want_queue=fila)
    return p, em


def parar(p):
    p.stop()
    p.join(3)
    return not p.is_alive()


# ---------------- testes ----------------
def t_parse_player():
    for e in (None, [], "x", {}):
        chk(sb.parse_player(e) is None, f"parse_player({e!r}) = None (sem dispositivo)")
    r = sb.parse_player({"device": None, "item": None, "is_playing": 1})
    chk(r is not None and r["volume"] is None and not r["can_volume"] and r["track_id"] is None and r["title"] == "",
        "parse_player: device e item nulos nao quebram")
    chk(sb.parse_player({"device": {"volume_percent": 150, "supports_volume": True}})["volume"] == 1.0,
        "volume acima de 100 vira 1.0")
    chk(sb.parse_player({"device": {"volume_percent": -5}})["volume"] == 0.0, "volume negativo vira 0.0")
    r = sb.parse_player({"device": {"volume_percent": "50"}})
    chk(r["volume"] is None and not r["can_volume"], "volume em texto e ignorado")
    chk(not sb.parse_player({"device": {"volume_percent": 50, "supports_volume": False}})["can_volume"],
        "supports_volume=false bloqueia volume")
    r = sb.parse_player({"item": {"id": "ep1", "type": "episode", "name": "Ep 1", "show": {"name": "Podcast X"}}})
    chk(r["track_id"] is None and r["title"] == "Ep 1" and r["artist"] == "Podcast X",
        "episodio de podcast: sem track_id (nao curte), artista = nome do programa")
    r = sb.parse_player({"item": {"id": "loc1", "type": "track", "is_local": True, "name": "Local",
                                  "artists": [{"name": "A"}]}})
    chk(r["track_id"] is None, "faixa local: sem track_id (nao curte)")
    chk(sb.parse_player({"repeat_state": "lixo"})["repeat"] == "off", "repeat invalido vira off")
    chk(sb.parse_player({"item": {"id": "t", "type": "track", "name": "N", "artists": None}})["artist"] == "",
        "artists null nao quebra")


def t_parse_queue():
    chk(sb.parse_queue(None) == [], "queue None -> []")
    chk(sb.parse_queue({"queue": None}) == [], "queue null -> []")
    chk(sb.parse_queue({"queue": [{"name": None}, "x", None]}) == [{"title": "—", "artist": ""}],
        "queue: itens invalidos ignorados, nome nulo vira —")
    chk(len(sb.parse_queue({"queue": [{"name": f"M{i}"} for i in range(35)]})) == 30, "queue: corta em 30 itens")


def t_http():
    st, j, _ = sb._http("GET", BASE + "/v1/teste/500", {"Authorization": "Bearer x"})
    chk(st == 500 and j == {"error": "x"}, "_http: 500 vira status com corpo")
    st, j, _ = sb._http("GET", BASE + "/v1/teste/html", {"Authorization": "Bearer x"})
    chk(st == 200 and j is None, "_http: 200 com HTML vira corpo None (sem excecao)")
    st, j, _ = sb._http("PUT", BASE + "/v1/teste/204", {"Authorization": "Bearer x"})
    chk(st == 204 and j is None, "_http: 204 sem corpo")
    try:
        sb._http("GET", "http://127.0.0.1:1/x", {})
        levantou = False
    except OSError:
        levantou = True
    chk(levantou, "_http: rede fora levanta OSError (tratado por quem chama)")


def t_status_api():
    reset()
    w = novo_web()
    for caminho, esperado in (("/teste/500", 500), ("/teste/403", 403), ("/nada", 404)):
        st, _ = w.request("GET", caminho)
        chk(st == esperado, f"request: {esperado} propagado ao chamador")
    chk(not w.blocked(), "erro 4xx/5xx nao bloqueia a API")
    chk(w.connected(), "erro 4xx/5xx nao derruba o login")


def t_429():
    reset()
    w = novo_web()
    st, _ = w.request("GET", "/teste/429")
    chk(st == 429 and w.blocked(), "429 com Retry-After invalido: bloqueia")
    chk(w.block_until - time.monotonic() > 3.5, "429 com Retry-After invalido espera 5 s (padrao)")
    n0 = len(S["hits"])
    st, _ = w.request("GET", "/me/player")
    chk(st == 429 and len(S["hits"]) == n0, "durante o bloqueio nao chama a API")
    w.block_until = 0.0


def t_sem_rede():
    reset()
    w = novo_web(api="http://127.0.0.1:1/v1")
    st, _ = w.request("GET", "/me/player")
    chk(st == 0, "sem rede: request devolve 0 sem excecao")
    chk(w.connected() and not w.revoked, "sem rede: login e mantido (nao e revogacao)")


def t_token_expirando():
    reset()
    w = novo_web(expira_em=-10)
    st, _ = w.request("GET", "/me/player")
    tok_pos = [h for h in S["hits"] if h[1] == "/api/token"]
    chk(st == 200 and len(tok_pos) == 1, "token expirado: renova antes de chamar a API")
    chk(S["hits"] and S["hits"][-1][2] == "Bearer AT1", "token expirado: usa o token novo")
    with open(w.path, encoding="utf-8") as f:
        chk(json.load(f).get("access_token") == "AT1", "token renovado e gravado no arquivo")


def t_refresh_500():
    reset()
    S["token"] = "500"
    w = novo_web(expira_em=-10)
    st, _ = w.request("GET", "/me/player")
    chk(st == 0 and w.connected() and w._d.get("refresh_token") == "RT1" and not w.revoked,
        "refresh 500: nao desloga, mantem refresh_token")
    S["token"] = "ok"


def t_invalid_grant():
    reset()
    S["token"] = "invalid"
    w = novo_web(expira_em=-10)
    st, _ = w.request("GET", "/me/player")
    chk(st == 0 and w.revoked and not w.connected(), "invalid_grant: marca revogado e desconecta")
    with open(w.path, encoding="utf-8") as f:
        chk("refresh_token" not in json.load(f), "invalid_grant: refresh_token apagado do arquivo")
    S["token"] = "ok"


def t_html_token():
    reset()
    S["token"] = "html"
    w = novo_web(expira_em=-10)
    st, _ = w.request("GET", "/me/player")
    chk(st == 0 and w.connected() and not w.revoked, "token: resposta 200 sem JSON nao quebra nem desloga")
    S["token"] = "ok"


def t_401():
    reset()
    S["n401"] = 1
    w = novo_web()
    st, _ = w.request("GET", "/me/player")
    chk(st == 200 and len([h for h in S["hits"] if h[1] == "/api/token"]) == 1,
        "401 uma vez: renova o token e repete a chamada")
    reset()
    S["n401"] = 10
    w = novo_web()
    st, _ = w.request("GET", "/me/player")
    chk(st == 401 and len([h for h in S["hits"] if h[1] == "/api/token"]) == 1,
        "401 sempre: tenta renovar 1 vez e devolve 401 (sem laco)")
    reset()


def t_log_sem_token():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        reset()
        S["token"] = "invalid"
        novo_web(expira_em=-10).request("GET", "/me/player")
        S["token"] = "500"
        novo_web(expira_em=-10).request("GET", "/me/player")
        S["token"] = "ok"
        novo_web(api="http://127.0.0.1:1/v1").request("GET", "/me/player")
        reset()
        S["n401"] = 10
        novo_web().request("GET", "/me/player")
        reset()
    txt = buf.getvalue()
    chk(not re.search(r"AT\d|RT\d|cid_teste|AT0|RT1", txt), "stdout de erros nao contem token nem client_id")
    chk(len(txt) > 0, "mensagens de erro foram impressas (teste nao e vazio)")


def t_poller_basico():
    reset()
    w = novo_web()
    p, em = poller(w, panel=True, on=True, fila=True)
    chk(esperar(lambda: em.tipos("player")), "poller: emite 'player' com a API falsa")
    chk(esperar(lambda: any(d[0] == "T1" for d in em.tipos("liked"))), "poller: busca curtida da faixa atual")
    S["queue"] = (200, {"queue": [{"name": f"M{i}", "artists": [{"name": "A"}]} for i in range(35)]})
    p.refresh()
    chk(esperar(lambda: any(len(q) == 30 for q in em.tipos("queue"))), "poller: fila com 35 itens chega com 30")
    S["queue"] = (204, None)
    p.refresh()
    chk(esperar(lambda: [] in em.tipos("queue")), "poller: fila 204 (vazia) emite lista vazia")
    S["queue"] = (500, {})
    n0 = len(em.tipos("queue"))
    p.refresh()
    time.sleep(0.8)
    chk(p.is_alive() and len(em.tipos("queue")) == n0, "poller: fila 500 nao emite nada e a thread segue viva")
    S["player"] = (500, {})
    p.refresh()
    time.sleep(0.5)
    chk(p.is_alive(), "poller: /me/player 500 nao mata a thread")
    S["player"] = (200, PLAYER_OK)
    n_q = len(em.tipos("queue"))
    S["player"] = (200, dict(PLAYER_OK, item={"id": "T2", "type": "track", "name": "Faixa 2",
                                              "artists": [{"name": "B"}]}))
    S["queue"] = (200, {"queue": [{"name": "Nova", "artists": [{"name": "C"}]}]})
    p.refresh()
    chk(esperar(lambda: any(d[0] == "T2" for d in em.tipos("liked"))), "troca de musica: busca curtida da nova faixa")
    chk(esperar(lambda: len(em.tipos("queue")) > n_q), "troca de musica com fila aberta: fila e atualizada")
    chk(parar(p), "stop: thread da API termina (nao fica presa)")
    reset()


def t_poller_500_200_html():
    reset()
    w = novo_web()
    S["player"] = (200, b"<html>")
    p, em = poller(w, panel=True, on=True)
    time.sleep(1.2)
    chk(p.is_alive() and em.tipos("player") == [], "player 200 com HTML: ignora a resposta (nao mostra 'sem dispositivo') e nao trava")
    chk(parar(p), "stop apos resposta invalida")
    reset()


def t_volume():
    reset()
    w = novo_web()
    p, em = poller(w, panel=True, on=True)
    esperar(lambda: em.tipos("player"))
    for i in range(0, 101):
        p.volume(i / 100)
    chk(esperar(lambda: S["vol"] and S["vol"][-1] == 100, 4), "volume: valor final (100%) chega ao Spotify")
    time.sleep(0.5)
    chk(len(S["vol"]) <= 4, f"volume: 101 ajustes rapidos viraram {len(S['vol'])} PUT (coalescido)")
    chk(parar(p), "volume: stop limpo")
    reset()


def t_curtir():
    reset()
    w = novo_web()
    S["libput"] = 404
    chk(w.set_liked("T1", True) is True and w._lib_mode == "tracks",
        "curtir: /me/library 404 -> cai para /me/tracks e funciona")
    reset()
    S["libput"] = 403
    S["tracksput"] = 403
    w = novo_web()
    chk(w.set_liked("T1", True) is False, "curtir: 403 devolve falha (sem tentar o outro endpoint)")
    reset()
    S["libput"] = 403
    p, em = poller(novo_web(), panel=False, on=True)
    p.command("like", "T1", True)
    chk(esperar(lambda: ("T1", False) in em.tipos("liked")), "curtir com falha: interface e revertida (coracao volta)")
    parar(p)
    reset()
    p, em = poller(novo_web(), panel=False, on=True)
    p.command("like", "T1", True)
    chk(esperar(lambda: ("T1", True) in em.tipos("liked")), "curtir OK: emite liked=True")
    parar(p)
    reset()


def t_thread_sobrevive():
    reset()
    w = novo_web()
    orig = w.request

    def boom(*a, **k):
        raise RuntimeError("falha simulada")
    w.request = boom
    p, em = poller(w, panel=True, on=True)
    time.sleep(1.5)
    chk(p.is_alive(), "thread da API sobrevive a excecao repetida")
    w.request = orig
    chk(esperar(lambda: em.tipos("player"), 4), "thread volta a funcionar depois da excecao")
    chk(parar(p), "stop apos excecoes")
    reset()


def t_rede_cai_no_meio():
    reset()
    w = novo_web(api="http://127.0.0.1:1/v1")
    p, em = poller(w, panel=True, on=True, fila=True)
    time.sleep(1.2)
    chk(p.is_alive() and em.tipos("player") == [], "rede cai durante uso: thread viva, nada emitido")
    chk(parar(p), "rede cai: stop limpo")
    reset()


def t_sem_login_silencioso():
    reset()
    w = novo_web(conectado=False)
    p, em = poller(w, panel=True, on=True, fila=True)
    p.volume(0.5)
    p.command("shuffle", True)
    p.refresh()
    n0 = len(S["hits"])
    time.sleep(1.2)
    chk(len(S["hits"]) == n0 and em.ev == [], "sem login: nenhuma chamada HTTP e nenhum evento")
    chk(not w.connected(), "sem login: connected() = False")
    chk(parar(p), "sem login: stop limpo")


def t_stop_daemon():
    reset()
    w = novo_web()
    p, em = poller(w, panel=True, on=True)
    chk(p.daemon, "thread da API e daemon (nao impede o app de fechar)")
    chk(parar(p), "desligar com a thread rodando: termina")
    reset()


def t_login_loopback():
    reset()
    orig_open = webbrowser.open

    def fake_open(url, *a, **k):
        st = up.parse_qs(up.urlparse(url).query)["state"][0]
        threading.Thread(target=lambda: ur.urlopen(
            f"http://127.0.0.1:8888/callback?code=CODIGO&state={st}", timeout=5).read(), daemon=True).start()
        return True
    webbrowser.open = fake_open
    try:
        w = novo_web(conectado=False)
        ok, msg = w.login(timeout=10)
        chk(ok and msg == "Teste" and w.connected() and w._d.get("refresh_token") == "RT2",
            "login PKCE (retorno falso em 8888): conecta e grava tokens")

        def fake_errado(url, *a, **k):
            threading.Thread(target=lambda: ur.urlopen(
                "http://127.0.0.1:8888/callback?code=X&state=errado", timeout=5).read(), daemon=True).start()
            return True
        webbrowser.open = fake_errado
        w2 = novo_web(conectado=False)
        ok2, _ = w2.login(timeout=10)
        chk(not ok2 and not w2.connected(), "login com state errado (CSRF): recusado e nada gravado")
    finally:
        webbrowser.open = orig_open
    reset()


TESTES = [("parse_player", t_parse_player), ("parse_queue", t_parse_queue), ("_http", t_http),
          ("status da API", t_status_api), ("429", t_429), ("sem rede", t_sem_rede),
          ("token expirando", t_token_expirando), ("refresh 500", t_refresh_500),
          ("invalid_grant", t_invalid_grant), ("token sem JSON", t_html_token), ("401", t_401),
          ("vazamento em log", t_log_sem_token), ("poller basico", t_poller_basico),
          ("poller resposta invalida", t_poller_500_200_html), ("volume rapido", t_volume),
          ("curtir", t_curtir), ("thread sobrevive", t_thread_sobrevive),
          ("rede cai no meio", t_rede_cai_no_meio), ("sem login silencioso", t_sem_login_silencioso),
          ("stop com thread", t_stop_daemon), ("login loopback", t_login_loopback)]

if __name__ == "__main__":
    t0 = time.time()
    for nome, fn in TESTES:
        out(f">>> {nome}")
        try:
            fn()
        except Exception as e:
            chk(False, f"{nome}: excecao inesperada {e!r}")
    SRV.shutdown()
    ok = sum(RES)
    falhas = len(RES) - ok
    out(f"RESULTADO: {ok} ok, {falhas} falhas")
    pasta_logs = os.path.join(PASTA, "logs")
    os.makedirs(pasta_logs, exist_ok=True)
    with open(os.path.join(SPOT, "spotify_barra.py"), "rb") as f:
        sha = hashlib.sha1(f.read()).hexdigest()
    reg = {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "versao": sha[:10],
           "suite": "bordas_api", "ok": ok, "falhas": falhas, "tempo_s": round(time.time() - t0, 1),
           "motivo": MOTIVO}
    with open(os.path.join(pasta_logs, "execucoes.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    with open(os.path.join(pasta_logs, "ultima_saida_bordas_api.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LINHAS) + "\n")
    sys.exit(0 if falhas == 0 else 1)
