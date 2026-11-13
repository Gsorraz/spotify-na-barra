# Testes da posição do mini player na barra (Controller._place_mini / _move_mini) em spotify_barra.py.
# Offscreen (QT_QPA_PLATFORM=offscreen): nenhuma janela aparece na tela, sem mouse, sem Controller completo
# (não sobe worker, API nem Taskbar real). APPDATA temporario.
# Uso: python teste_mini_posicao.py "<motivo>"
import os, sys, time, types, tempfile, hashlib, datetime, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="sb_mini_")
PASTA = os.path.dirname(os.path.abspath(__file__))
SPOT = os.path.dirname(PASTA)
sys.path.insert(0, SPOT)
import spotify_barra as sb
from PySide6.QtCore import QRect, QObject
from PySide6.QtWidgets import QApplication, QWidget

MOTIVO = sys.argv[1] if len(sys.argv) > 1 else "posicao do mini"
RES = []


def chk(cond, desc):
    RES.append(bool(cond))
    print(("  ok    " if cond else "FALHA ") + desc, flush=True)


def aviso(desc):
    print("  AVISO " + desc, flush=True)


class MiniFake(QWidget):
    def __init__(self):
        super().__init__()
        self.dragging = False


class CtlFake(QObject):
    """Controller simulado: so os atributos usados por _place_mini/_move_mini."""
    def __init__(self, mini):
        super().__init__()
        self.mini = mini
        self.cfg = {"manual_offset": None}
        self._mini_target = None
        self._mini_anim = None
        self._place_mini = types.MethodType(sb.Controller._place_mini, self)
        self._move_mini = types.MethodType(sb.Controller._move_mini, self)


app = QApplication.instance() or QApplication([])
TB = QRect(0, 1040, 1921, 40)          # barra de tarefas
TRAY_LEFT = 1590                       # onde começa a bandeja (tb centro = 960)
CENTRO = TB.center().x()


def info(icons_right, tray_left=TRAY_LEFT):
    return {"tb": TB, "tray_left": tray_left, "icons_right": icons_right, "hidden": False, "fullscreen": False}


def novo():
    m = MiniFake()
    m.resize(sb.MiniBar.W, 40)
    c = CtlFake(m)
    return c, m


def ultimo_x_w(c):
    return c._mini_target.x(), c._mini_target.width()


sb.DEMO = True   # logica pura primeiro (sem animação)
print(">>> mini: posicao (logica)", flush=True)
chk(sb.MINI_GAP == 14, "constante MINI_GAP == 14")

# (a) posição manual longe dos ícones -> não se mexe
c, m = novo()
c.cfg["manual_offset"] = -300                       # x = 960-300 = 660
c._place_mini(info(icons_right=400))
x, w = ultimo_x_w(c)
chk(x == 660, f"(a) manual_offset com ícones longe (400): x={x}, esperado 660 (não se mexe)")

# (b) ícones avançam até chegar perto -> empurra para icons_right + 14
c._place_mini(info(icons_right=600)); x, _ = ultimo_x_w(c)
chk(x == 660, f"(b1) ícones em 600 (ainda longe): x={x}, esperado 660")
c._place_mini(info(icons_right=700)); x, _ = ultimo_x_w(c)
chk(x == 714, f"(b2) ícones em 700: x={x}, esperado 714 (700+14, empurrado)")
c._place_mini(info(icons_right=800)); x, _ = ultimo_x_w(c)
chk(x == 814, f"(b3) ícones em 800: x={x}, esperado 814")

# (c) ícones voltam -> volta para a posição preferida
c._place_mini(info(icons_right=400)); x, _ = ultimo_x_w(c)
chk(x == 660, f"(c) ícones voltam para 400: x={x}, esperado 660 (posição preferida)")

# (d) sem espaço até a bandeja -> largura encolhe até 220 e x nunca passa de tray_left-10
c, m = novo()
c.cfg["manual_offset"] = 600                        # x = 1560, w=320 -> passa da bandeja
c._place_mini(info(icons_right=400)); x, w = ultimo_x_w(c)
chk(w == 220, f"(d1) sem espaço: largura={w}, esperado 220")
chk(x + w <= TRAY_LEFT - 10, f"(d2) x+w={x+w} <= tray_left-10={TRAY_LEFT-10}")
c._place_mini(info(icons_right=1300)); x, w = ultimo_x_w(c)
chk(x + w <= TRAY_LEFT - 10 and w == 220, f"(d3) ícones em 1300 apertando: x={x}, w={w}, x+w<={TRAY_LEFT-10}")
# achado: com a bandeja quase encostada, o clamp puxa o mini para ESQUERDA dos ícones
c._place_mini(info(icons_right=1500)); x, w = ultimo_x_w(c)
chk(x + w <= TRAY_LEFT - 10, f"(d4) ícones em 1500: x+w={x+w} <= {TRAY_LEFT-10} (limite da bandeja respeitado)")
if x < 1500 + sb.MINI_GAP:
    aviso(f"(d4) sem espaço, o mini (x={x}) fica SOBREPOSTO aos ícones (fim em 1500); "
          f"a regra icons_right+MINI_GAP={1500+sb.MINI_GAP} é desfeita pelo limite da bandeja")

# (e) icons_right None -> sem erro
c, m = novo()
try:
    c._place_mini(info(icons_right=None)); x, w = ultimo_x_w(c)
    chk(x == CENTRO + 250, f"(e1) icons_right None, modo auto: x={x}, esperado {CENTRO+250} (centro+250)")
    c.cfg["manual_offset"] = -200
    c._place_mini(info(icons_right=None)); x, w = ultimo_x_w(c)
    chk(x == CENTRO - 200, f"(e2) icons_right None, manual: x={x}, esperado {CENTRO-200}")
    ok_e = True
except Exception as e:
    ok_e = False
    chk(False, f"(e) icons_right None lançou {type(e).__name__}: {e}")
chk(ok_e, "(e) icons_right None sem erro")

# (f) modo automático -> icons_right + 14 (e nunca menos que o empurrão)
c, m = novo()
c._place_mini(info(icons_right=700)); x, _ = ultimo_x_w(c)
chk(x == 714, f"(f1) auto, ícones 700: x={x}, esperado 714")
c._place_mini(info(icons_right=400)); x, _ = ultimo_x_w(c)
chk(x == 414, f"(f2) auto, ícones 400: x={x}, esperado 414")

# drag: enquanto arrasta não mexe e zera o alvo
c, m = novo()
c._place_mini(info(icons_right=400))
m.dragging = True
c._place_mini(info(icons_right=900))
chk(c._mini_target is None, "(g) arrastando: _place_mini zera _mini_target e não move")
m.dragging = False

print(">>> mini: caminho animado (DEMO desligado, mini visível offscreen)", flush=True)
sb.DEMO = False
c, m = novo()
c.cfg["manual_offset"] = -300                        # preferida = 660
m.setGeometry(QRect(660, 1044, sb.MiniBar.W, 32))
m.show(); app.processEvents()
chk(m.isVisible(), "(h0) mini visível (offscreen)")
c._place_mini(info(icons_right=700))                 # alvo 714 (salto 54 px) -> anima
anim = c._mini_anim
chk(anim is not None and anim.endValue().x() == 714, "(h1) salto de 660 para 714 cria animação com destino 714")
c._place_mini(info(icons_right=700)); c._place_mini(info(icons_right=700))
chk(c._mini_anim is anim, "(h2) ticks repetidos com mesmo alvo não reiniciam a animação")
amostras = []
t0 = time.monotonic()
while time.monotonic() - t0 < 0.5:
    app.processEvents(); time.sleep(0.01)
    amostras.append(m.geometry().x())
meio = [v for v in amostras if 660 < v < 714]
chk(len(meio) > 0, f"(h3) durante a animação houve valor intermediário entre 660 e 714: {sorted(set(amostras))[:12]}")
chk(m.geometry().x() == 714, f"(h4) após 500 ms x={m.geometry().x()}, esperado 714")

c._place_mini(info(icons_right=1200))                # salto > 400 px -> sem animação
chk(m.geometry().x() == 1214 and c._mini_target.x() == 1214,
    f"(h5) salto > 400 px vai direto: geometry.x={m.geometry().x()}, alvo=1214")

sb.DEMO = True
m.setGeometry(QRect(660, 1044, sb.MiniBar.W, 32))
c._place_mini(info(icons_right=700))                 # DEMO: sem animação, direto
chk(m.geometry().x() == 714, f"(h6) DEMO: sem animação, x={m.geometry().x()} direto (esperado 714)")
sb.DEMO = False
m.hide()

total, ok = len(RES), sum(RES)
falhas = total - ok
print(f"\nRESUMO mini_posicao: {ok} ok, {falhas} falha(s)", flush=True)
registro = {
    "quando": datetime.datetime.now().isoformat(timespec="seconds"),
    "versao": hashlib.sha1(open(os.path.join(SPOT, "spotify_barra.py"), "rb").read()).hexdigest()[:10],
    "suite": "mini_posicao", "ok": ok, "falhas": falhas, "motivo": MOTIVO,
}
with open(os.path.join(PASTA, "logs", "execucoes.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(registro, ensure_ascii=False) + "\n")
sys.exit(0 if falhas == 0 else 1)
