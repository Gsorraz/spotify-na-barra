# -*- coding: utf-8 -*-
"""
Spotify na Barra — mini player que vive na barra de tarefas do Windows.

- Aparece sozinho no espaço vazio da barra (à direita dos ícones) quando o
  Spotify começa a tocar, e some quando o Spotify fecha.
- Clique no mini player para abrir o painel completo (capa, progresso,
  letra sincronizada, volume, saída de áudio, timer).
- Clique direito: configurações. Arraste para mudar a posição na barra.

Controla o Spotify de desktop pelos controles de mídia do Windows (SMTC).
Rodar sem Windows (ou com SB_DEMO=1) abre um modo demonstração.
"""
from __future__ import annotations

import asyncio
import copy
import ctypes
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from PySide6.QtCore import (QBuffer, QByteArray, QEasingCurve, QEvent, QIODevice, QObject, QPoint,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

APP_NAME = "Spotify na Barra"
APP_ID = "SpotifyNaBarra"
IS_WIN = sys.platform == "win32"
DEMO = os.environ.get("SB_DEMO") == "1" or not IS_WIN

# ============================================================================
# Configuração
# ============================================================================
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)
CFG_FILE = os.path.join(APP_DIR, "config.json")
DEFAULTS = {
    "accent_mode": "cover",     # cover | orange | green
    "hide_on_pause": False,     # some da barra quando pausa
    "other_players": False,     # também mostra outros players (navegador etc.)
    "manual_offset": None,      # deslocamento manual (px) a partir do centro da barra
    "offsets": {},              # ajuste de sincronização de letra por música
}


class Config(dict):
    def __init__(self):
        super().__init__(copy.deepcopy(DEFAULTS))
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.update(data)
        except Exception:
            pass
        self._sanitize()

    def _sanitize(self):
        """Config editada à mão/corrompida não pode derrubar o app."""
        if self["accent_mode"] not in ("cover", "orange", "green"):
            self["accent_mode"] = DEFAULTS["accent_mode"]
        for k in ("hide_on_pause", "other_players"):
            self[k] = bool(self[k])
        if not isinstance(self["offsets"], dict):
            self["offsets"] = {}
        if isinstance(self["manual_offset"], bool) or not isinstance(self["manual_offset"], (int, float, type(None))):
            self["manual_offset"] = None

    def save(self):
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            tmp = CFG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=1)
            os.replace(tmp, CFG_FILE)  # gravação atômica: queda de energia não corrompe
        except Exception:
            pass


def setup_log():
    """Sem console (pythonw/.exe --windowed) os print() somem; grava em arquivo para diagnóstico."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        path = os.path.join(APP_DIR, "log.txt")
        if os.path.exists(path) and os.path.getsize(path) > 200_000:
            os.replace(path, path + ".old")
        sys.stdout = sys.stderr = open(path, "a", encoding="utf-8", buffering=1)
        print("\n---", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "---")
    except Exception:
        pass


# ============================================================================
# Ícones (SVG) e fontes
# ============================================================================
ICONS = {
    "note": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M10 3.5v10.05A3.5 3.5 0 1 0 12 16.7V8h5.5V3.5H10Z"/></svg>',
    "grid": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/></svg>',
    "timer": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12.5" r="8.5"/><path d="M12 4V2.5M12 12.5l-4-4"/></svg>',
    "gear": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M10.3 2.8h3.4l.5 2.6 1.9 1.1 2.5-.9 1.7 3-2 1.7v2.2l2 1.7-1.7 3-2.5-.9-1.9 1.1-.5 2.6h-3.4l-.5-2.6-1.9-1.1-2.5.9-1.7-3 2-1.7v-2.2l-2-1.7 1.7-3 2.5.9 1.9-1.1z"/><circle cx="12" cy="12" r="3"/></svg>',
    "vol": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M3 9.5h3.5L11 5.5v13l-4.5-4H3z"/><path d="M14.5 9a4 4 0 0 1 0 6M17 6.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    "mute": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M3 9.5h3.5L11 5.5v13l-4.5-4H3z"/><path d="M15 9.5l5 5M20 9.5l-5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    "prev": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M5 4.5h3v15H5zM20 4.8v14.4L8.8 12z"/></svg>',
    "next": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M16 4.5h3v15h-3zM4 4.8v14.4L15.2 12z"/></svg>',
    "play": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M7 4.5v15l12.5-7.5z"/></svg>',
    "pause": '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z"/></svg>',
    "more": '<svg viewBox="0 0 34 24"><circle cx="5" cy="12" r="2" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/><circle cx="19" cy="12" r="2" fill="currentColor"/><path d="M25 10l3.5 3.5L32 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "lyrics": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z"/><path d="M9 8.5v2.5M13 8.5v2.5" stroke-linecap="round"/></svg>',
    "queue": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8.5 6h12M8.5 12h12M8.5 18h12"/><circle cx="4" cy="6" r=".6" fill="currentColor"/><circle cx="4" cy="12" r=".6" fill="currentColor"/><circle cx="4" cy="18" r=".6" fill="currentColor"/></svg>',
    "device": '<svg viewBox="0 0 34 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5.6 16.5a8.5 8.5 0 1 1 12.8 0"/><path d="M8.3 14a5 5 0 1 1 7.4 0"/><path d="M12 14.5l4 5.5H8z" fill="currentColor"/><path d="M25 10.5l3.5 3.5 3.5-3.5" stroke-width="1.8"/></svg>',
    "sync": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
}

_pix_cache: dict = {}


def svg_pixmap(name: str, color: str = "#ffffff", size: int = 22) -> QPixmap:
    key = (name, color, size)
    if key in _pix_cache:
        return _pix_cache[key]
    svg = ICONS[name].replace("currentColor", color)
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    vb = r.viewBoxF()
    ratio = vb.width() / vb.height() if vb.height() else 1
    w, h = (size * ratio, size) if ratio >= 1 else (size, size / ratio)
    pm = QPixmap(int(w * 2), int(h * 2))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(2)
    _pix_cache[key] = pm
    return pm


def font(px: int, weight=QFont.Normal) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"])
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def fmt_time(s: float) -> str:
    s = max(0, int(s or 0))
    h, m, x = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def rounded_pixmap(img: QImage, size: int, radius: float) -> QPixmap:
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size * dpr, size * dpr), radius * dpr, radius * dpr)
    p.setClipPath(path)
    src = img.scaled(size * dpr, size * dpr, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    p.drawImage(0, 0, src, (src.width() - size * dpr) // 2, (src.height() - size * dpr) // 2)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def accent_from_image(img: QImage) -> QColor:
    small = img.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
    best, best_score, tot, n = None, -1.0, [0, 0, 0], 0
    for y in range(small.height()):
        for x in range(small.width()):
            c = QColor(small.pixel(x, y))
            r, g, b = c.red(), c.green(), c.blue()
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / mx if mx else 0
            light = (mx + mn) / 510
            score = sat * (1 - abs(light - 0.5) * 1.6)
            tot[0] += r; tot[1] += g; tot[2] += b; n += 1
            if score > best_score:
                best_score, best = score, (r, g, b)
    rgb = list(best) if best_score > 0.25 else [v // max(n, 1) for v in tot]
    mx = max(rgb)
    if mx < 20:  # capa preta: não há matiz para realçar, usa a cor padrão
        return QColor("#e8572a")
    if mx < 140:
        rgb = [min(255, int(v * 140 / max(mx, 1))) for v in rgb]
    return QColor(*rgb)


MENU_QSS = """
QMenu{background:#1c1c1e;border:1px solid #38383a;border-radius:12px;padding:6px;color:#f2f2f7}
QMenu::item{padding:8px 26px 8px 12px;border-radius:7px;background:transparent}
QMenu::item:selected{background:#2c2c2e}
QMenu::item:disabled{color:#8e8e93}
QMenu::separator{height:1px;background:#38383a;margin:5px 8px}
QMenu::right-arrow{width:8px;height:8px}
"""


def make_menu(parent=None) -> QMenu:
    m = QMenu(parent)
    m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    m.setAttribute(Qt.WA_TranslucentBackground)
    m.setStyleSheet(MENU_QSS)
    m.setFont(font(14))
    return m


def menu_item(menu: QMenu, text: str, fn, checked=None, enabled=True):
    label = (("✓   " if checked else "     ") + text) if checked is not None else text
    a = menu.addAction(label)
    a.setEnabled(enabled)
    a.triggered.connect(fn)
    return a


def open_spotify():
    try:
        if IS_WIN:
            os.startfile("spotify:")
        else:
            import webbrowser
            webbrowser.open("https://open.spotify.com")
    except Exception:
        import webbrowser
        webbrowser.open("https://open.spotify.com")


# ============================================================================
# Fonte de mídia: controles de mídia do Windows (SMTC)
# ============================================================================
class MediaWorker(QThread):
    state = Signal(object)          # dict ou None
    thumb = Signal(bytes, str)      # imagem, chave da música

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.loop = None
        self.session = None
        self.running = True
        self._poke = None

    # --- API pública (thread principal) ---
    def cmd(self, name, arg=None):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cmd(name, arg), self.loop)

    def stop(self):
        self.running = False

    # --- Thread ---
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:  # pragma: no cover
            print("MediaWorker:", e)

    def _imports(self):
        try:
            from winrt.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as MM
            from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
            try:
                from winrt.windows.media import MediaPlaybackAutoRepeatMode as RM
            except Exception:
                RM = None
        except ImportError:
            from winsdk.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as MM
            from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
            try:
                from winsdk.windows.media import MediaPlaybackAutoRepeatMode as RM
            except Exception:
                RM = None
        self.MM, self.Buffer, self.DataReader, self.ISO, self.RM = MM, Buffer, DataReader, InputStreamOptions, RM

    def _pick(self, mgr):
        try:
            for s in mgr.get_sessions():
                if "spotify" in (s.source_app_user_model_id or "").lower():
                    return s
        except Exception:
            pass
        if self.cfg.get("other_players"):
            try:
                return mgr.get_current_session()
            except Exception:
                return None
        return None

    async def _read_thumb(self, ref) -> bytes | None:
        stream = await ref.open_read_async()
        size = int(getattr(stream, "size", 0) or 0) or 5_000_000
        buf = self.Buffer(size)
        await stream.read_async(buf, size, self.ISO.READ_AHEAD)
        n = int(buf.length)
        if not n:
            return None
        try:
            return bytes(memoryview(buf))[:n]
        except Exception:
            pass
        reader = self.DataReader.from_buffer(buf)
        try:
            out = reader.read_bytes(n)
            if out is not None:
                return bytes(out)
        except TypeError:
            pass
        arr = bytearray(n)
        reader.read_bytes(arr)
        return bytes(arr)

    async def _main(self):
        self._imports()
        self._poke = asyncio.Event()
        mgr = await self.MM.request_async()
        last_key, thumb_tries, last_thumb_hash, last_thumb_key = None, [], None, None
        while self.running:
            try:
                sess = self._pick(mgr)
                self.session = sess
                if not sess:
                    self.state.emit(None)
                    last_key = None
                else:
                    props = await sess.try_get_media_properties_async()
                    info = sess.get_playback_info()
                    tl = sess.get_timeline_properties()
                    playing = int(info.playback_status) == 4
                    start = tl.start_time.total_seconds() if tl.start_time else 0
                    dur = (tl.end_time.total_seconds() if tl.end_time else 0) - start
                    pos = (tl.position.total_seconds() if tl.position else 0) - start
                    lu = tl.last_updated_time
                    if playing and lu:
                        if lu.tzinfo is None:
                            lu = lu.replace(tzinfo=timezone.utc)
                        delta = (datetime.now(timezone.utc) - lu).total_seconds()
                        if 0 < delta < 6 * 3600:
                            pos += delta
                    if dur > 0:
                        pos = min(pos, dur)
                    title = props.title or ""
                    artist = props.artist or props.album_artist or ""
                    album = props.album_title or ""
                    key = f"{title}|{artist}|{album}"
                    rep = info.auto_repeat_mode
                    st = {
                        "app": sess.source_app_user_model_id or "",
                        "title": title, "artist": artist, "album": album,
                        "playing": playing, "position": max(0.0, pos), "duration": max(0.0, dur),
                        "shuffle": bool(info.is_shuffle_active) if info.is_shuffle_active is not None else None,
                        "repeat": int(rep) if rep is not None else None,
                        "key": key, "_t": time.monotonic(),
                    }
                    self.state.emit(st)
                    now = time.monotonic()
                    if key != last_key:
                        last_key = key
                        thumb_tries = [now, now + 1.5, now + 4]
                    if thumb_tries and now >= thumb_tries[0]:
                        thumb_tries.pop(0)
                        if props.thumbnail:
                            try:
                                data = await self._read_thumb(props.thumbnail)
                                h = hash(data) if data else None
                                # mesma capa em faixa nova (mesmo álbum) também precisa ser reenviada
                                if data and (h != last_thumb_hash or key != last_thumb_key):
                                    last_thumb_hash, last_thumb_key = h, key
                                    self.thumb.emit(data, key)
                            except Exception as e:
                                print("thumb:", e)
            except Exception as e:
                print("poll:", e)
            try:
                await asyncio.wait_for(self._poke.wait(), 0.4)
            except asyncio.TimeoutError:
                pass
            self._poke.clear()

    async def _cmd(self, name, arg):
        s = self.session
        if not s:
            return
        try:
            if name == "playpause":
                await s.try_toggle_play_pause_async()
            elif name == "pause":
                await s.try_pause_async()
            elif name == "next":
                await s.try_skip_next_async()
            elif name == "prev":
                await s.try_skip_previous_async()
            elif name == "seek":
                await s.try_change_playback_position_async(int(float(arg) * 10_000_000))
            elif name == "shuffle":
                await s.try_change_shuffle_active_async(bool(arg))
            elif name == "repeat" and self.RM is not None:
                await s.try_change_auto_repeat_mode_async(self.RM(int(arg)))
        except Exception as e:
            print("cmd", name, e)
        await asyncio.sleep(0.15)
        if self._poke:
            self._poke.set()


class DemoWorker(QObject):
    """Simula o Spotify para testar o visual fora do Windows."""
    state = Signal(object)
    thumb = Signal(bytes, str)
    TRACKS = [("Olhos certos", "Detonautas", "Roque Clube", 261, (200, 80, 30)),
              ("De Mais Ninguém", "Edu Ribeiro", "Luau", 186, (220, 160, 40)),
              ("Green Eyes", "Coldplay", "A Rush of Blood to the Head", 222, (210, 210, 210))]

    def __init__(self, cfg):
        super().__init__()
        self.i, self.pos, self.playing, self.t0 = 0, 121.0, True, time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._emit)

    def start(self):
        self.timer.start(400)
        QTimer.singleShot(50, self._emit_thumb)

    def stop(self):
        self.timer.stop()

    def wait(self, *_):
        return True

    def _cur(self):
        return self.pos + ((time.monotonic() - self.t0) if self.playing else 0)

    def _emit(self):
        t = self.TRACKS[self.i]
        p = self._cur()
        if p >= t[3]:
            self.cmd("next")
            return
        self.state.emit({"app": "Spotify.exe", "title": t[0], "artist": t[1], "album": t[2], "playing": self.playing,
                         "position": p, "duration": t[3], "shuffle": False, "repeat": 0,
                         "key": f"{t[0]}|{t[1]}|{t[2]}", "_t": time.monotonic()})

    def _emit_thumb(self):
        t = self.TRACKS[self.i]
        img = QImage(300, 300, QImage.Format_RGB32)
        p = QPainter(img)
        p.fillRect(img.rect(), QColor(25, 28, 36))
        for k in range(14):
            c = QColor(*t[4]).lighter(80 + k * 6)
            p.setBrush(c); p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(40 + k * 18, 60 + k * 14), 60 - k * 2, 60 - k * 2)
        p.end()
        ba = QByteArray(); b = QBuffer(ba); b.open(QIODevice.WriteOnly); img.save(b, "PNG")
        self.thumb.emit(bytes(ba), f"{t[0]}|{t[1]}|{t[2]}")

    def cmd(self, name, arg=None):
        if name == "playpause":
            self.pos = self._cur(); self.t0 = time.monotonic(); self.playing = not self.playing
        elif name == "pause":
            self.pos = self._cur(); self.t0 = time.monotonic(); self.playing = False
        elif name in ("next", "prev"):
            self.i = (self.i + (1 if name == "next" else -1)) % len(self.TRACKS)
            self.pos, self.t0 = 0, time.monotonic()
            self._emit_thumb()
        elif name == "seek":
            self.pos, self.t0 = float(arg), time.monotonic()
        self._emit()


# ============================================================================
# Áudio: volume do Spotify no mixer e saída de áudio do Windows
# ============================================================================
class Audio:
    def __init__(self):
        self.ok = False
        self._demo_vol, self._demo_mute = 0.35, False
        if DEMO:
            return
        try:
            from pycaw.pycaw import AudioUtilities  # noqa
            self.AU = AudioUtilities
            self.ok = True
        except Exception as e:
            print("pycaw:", e)

    def _sessions(self):
        out = []
        try:
            for s in self.AU.GetAllSessions():
                try:
                    if s.Process and s.Process.name().lower() == "spotify.exe":
                        out.append(s)
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def get(self):
        if DEMO:
            return (0.0 if self._demo_mute else self._demo_vol), self._demo_mute
        if not self.ok:
            return None
        ss = self._sessions()
        if not ss:
            return None
        try:
            v = ss[0].SimpleAudioVolume
            mute = bool(v.GetMute())
            return (0.0 if mute else float(v.GetMasterVolume())), mute
        except Exception:  # sessão de áudio expirou entre a listagem e a leitura
            return None

    def set(self, value: float):
        value = max(0.0, min(1.0, value))
        if DEMO:
            self._demo_vol, self._demo_mute = value, value == 0
            return
        for s in self._sessions():
            try:
                v = s.SimpleAudioVolume
                v.SetMasterVolume(value, None)
                v.SetMute(1 if value == 0 else 0, None)
            except Exception:
                pass

    def toggle_mute(self):
        if DEMO:
            self._demo_mute = not self._demo_mute
            return
        ss = self._sessions()
        if not ss:
            return
        try:
            m = 0 if ss[0].SimpleAudioVolume.GetMute() else 1
        except Exception:
            return
        for s in ss:
            try:
                s.SimpleAudioVolume.SetMute(m, None)
            except Exception:
                pass

    # --- Dispositivos de saída ---
    def devices(self):
        """[(id, nome)], id_padrao"""
        if DEMO:
            return [("a", "Alto-falantes (Realtek)"), ("b", "MAG 341C OLED")], "a"
        try:
            enum = self.AU.GetDeviceEnumerator()
            coll = enum.EnumAudioEndpoints(0, 1)  # eRender, ACTIVE
            out = []
            for i in range(coll.GetCount()):
                d = coll.Item(i)
                try:
                    name = self.AU.CreateDevice(d).FriendlyName
                except Exception:
                    name = "Dispositivo"
                out.append((d.GetId(), name))
            default = enum.GetDefaultAudioEndpoint(0, 1).GetId()
            return out, default
        except Exception as e:
            print("devices:", e)
            return [], None

    def set_default(self, dev_id: str) -> bool:
        if DEMO:
            return True
        try:
            from ctypes import c_int, c_wchar_p
            import comtypes
            from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

            class IPolicyConfig(IUnknown):
                _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
                _methods_ = [COMMETHOD([], HRESULT, f"Unused{i}") for i in range(10)] + [
                    COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                              (["in"], c_wchar_p, "deviceId"), (["in"], c_int, "role")),
                ]

            pc = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"),
                                           IPolicyConfig, comtypes.CLSCTX_ALL)
            for role in (0, 1, 2):
                pc.SetDefaultEndpoint(dev_id, role)
            return True
        except Exception as e:
            print("set_default:", e)
            return False


# ============================================================================
# Barra de tarefas: geometria, espaço livre após os ícones, tela cheia
# ============================================================================
class Taskbar:
    def __init__(self):
        self.icons_right_phys = None
        self.user32 = self._load_user32() if IS_WIN else None
        if IS_WIN and not DEMO:
            threading.Thread(target=self._uia_loop, daemon=True).start()

    @staticmethod
    def _load_user32():
        """user32 com tipos declarados. Sem argtypes, o ctypes passa HWND_TOPMOST (-1) como int de
        32 bits e o SetWindowPos falha em Python 64 bits (erro 1400): o mini ficava atrás da barra."""
        from ctypes import wintypes as wt
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.argtypes, u.FindWindowW.restype = [wt.LPCWSTR, wt.LPCWSTR], wt.HWND
        u.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowExW.restype = wt.HWND
        u.GetWindowRect.argtypes, u.GetWindowRect.restype = [wt.HWND, ctypes.c_void_p], wt.BOOL
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        u.SetWindowPos.restype = wt.BOOL
        return u

    @staticmethod
    def _dpr():
        scr = QGuiApplication.primaryScreen()
        return scr.devicePixelRatio() if scr else 1.0

    def _rect(self, hwnd):
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if hwnd and self.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return r
        return None

    def _tray_left_phys(self, tb_hwnd, tb_rect):
        tray = self.user32.FindWindowExW(tb_hwnd, 0, "TrayNotifyWnd", None)
        r = self._rect(tray)
        if r and r.right > r.left and r.left > tb_rect.left:
            return r.left
        return tb_rect.left + int((tb_rect.right - tb_rect.left) * 0.72)

    def _uia_loop(self):
        """Descobre onde termina o último ícone de app (UI Automation)."""
        try:
            import comtypes
            import comtypes.client
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:  # o import do comtypes já inicializou o COM nesta thread (modo diferente): serve
                pass
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as U
            uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
            cond = uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, U.UIA_ButtonControlTypeId)
        except Exception as e:
            print("UIA indisponível:", e)
            return
        while True:
            try:
                h = self.user32.FindWindowW("Shell_TrayWnd", None)
                tb = self._rect(h)
                if tb:
                    tray_left = self._tray_left_phys(h, tb)
                    arr = uia.ElementFromHandle(h).FindAll(U.TreeScope_Descendants, cond)
                    best_task, best_any = None, None
                    for i in range(arr.Length):
                        el = arr.GetElement(i)
                        r = el.CurrentBoundingRectangle
                        if r.right <= r.left or r.right > tray_left - 4 or r.top < tb.top - 2:
                            continue
                        cls = el.CurrentClassName or ""
                        if "TaskListButton" in cls:
                            best_task = max(best_task or 0, r.right)
                        best_any = max(best_any or 0, r.right)
                    self.icons_right_phys = best_task or best_any
            except Exception:
                pass
            time.sleep(2)

    def info(self):
        """dict: tb (QRect lógico), tray_left, icons_right, hidden, fullscreen"""
        scr = QGuiApplication.primaryScreen()
        sg = scr.geometry()
        if DEMO or not IS_WIN:
            tb = QRect(sg.left(), sg.bottom() - 47, sg.width(), 48)
            return {"tb": tb, "tray_left": sg.right() - 330, "icons_right": sg.center().x() + 230,
                    "hidden": False, "fullscreen": False}
        dpr = self._dpr()
        h = self.user32.FindWindowW("Shell_TrayWnd", None)
        r = self._rect(h)
        if not r:
            tb = QRect(sg.left(), sg.bottom() - 47, sg.width(), 48)
            return {"tb": tb, "tray_left": sg.right() - 330, "icons_right": None, "hidden": False, "fullscreen": False}
        tb = QRect(int(r.left / dpr), int(r.top / dpr), int((r.right - r.left) / dpr), int((r.bottom - r.top) / dpr))
        tray_left = int(self._tray_left_phys(h, r) / dpr)
        icons_right = int(self.icons_right_phys / dpr) if self.icons_right_phys else None
        hidden = tb.top() >= sg.bottom() - 3
        fs = False
        try:
            st = ctypes.c_int(0)
            ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st))
            fs = st.value in (2, 3, 4)  # ocupado / D3D tela cheia / apresentação
        except Exception:
            pass
        return {"tb": tb, "tray_left": tray_left, "icons_right": icons_right, "hidden": hidden, "fullscreen": fs}

    def keep_on_top(self, widget: QWidget):
        if not IS_WIN or DEMO:
            return
        try:
            hwnd = int(widget.winId())
            # HWND_TOPMOST, SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_NOOWNERZORDER
            self.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200)
        except Exception:
            pass


# ============================================================================
# Letras (LRCLIB — gratuito, sem chave)
# ============================================================================
def _clean_title(t: str) -> str:
    t = re.sub(r"\s*[-–]\s*(remaster(ed)?|ao vivo|live|versão|version|radio edit|mono|stereo).*$", "", t or "", flags=re.I)
    t = re.sub(r"\s*\((feat\.?|with|part\.?|ft\.?)[^)]*\)", "", t, flags=re.I)
    return t.strip()


def _parse_lrc(lrc: str):
    out = []
    for raw in lrc.splitlines():
        tags = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw)
        if not tags:
            continue
        text = re.sub(r"\[[^\]]*\]|<\d+:\d+(?:\.\d+)?>", "", raw).strip()  # tags de tempo e de palavra (LRC estendido)
        for m, s in tags:
            out.append((int(m) * 60 + float(s), text))
    return sorted(out, key=lambda x: x[0])


def fetch_lyrics(title, artist, album, duration):
    first_artist = re.split(r",|&| e | feat", artist or "", flags=re.I)[0].strip()
    ua = {"User-Agent": "SpotifyNaBarra/1.0", "Lrclib-Client": "SpotifyNaBarra/1.0"}

    def get(url):
        req = urllib.request.Request(url, headers=ua)
        for attempt in (0, 1):  # o LRCLIB responde 503/timeout de vez em quando: uma nova tentativa resolve
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt:
                    raise
            except OSError:  # timeout / conexão (URLError é subclasse)
                if attempt:
                    raise
            time.sleep(0.8)

    def pack(d):
        return {"synced": _parse_lrc(d["syncedLyrics"]) if d.get("syncedLyrics") else None,
                "plain": d.get("plainLyrics"), "instrumental": bool(d.get("instrumental"))}

    # artista só com o primeiro nome ("Simon") e completo ("Simon & Garfunkel"): o cadastro varia
    artists = [first_artist] + ([artist.strip()] if artist and artist.strip() != first_artist else [])
    urls = []
    if duration:
        urls.append("https://lrclib.net/api/get?" + urllib.parse.urlencode(
            {"track_name": title, "artist_name": first_artist, "album_name": album or "", "duration": round(duration)}))
    for a in artists:
        urls.append("https://lrclib.net/api/get?" + urllib.parse.urlencode(
            {"track_name": _clean_title(title), "artist_name": a}))
    for u in urls:
        try:
            return pack(get(u))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    for a in artists:
        lst = get("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"track_name": _clean_title(title), "artist_name": a}))
        if isinstance(lst, list) and lst:
            if duration:  # versão com duração muito diferente (ao vivo/remix) dessincroniza a letra
                near = [x for x in lst if abs((x.get("duration") or 0) - duration) <= 4]
                lst = near or lst
            best = next((x for x in lst if x.get("syncedLyrics")), lst[0])
            return pack(best)
    return {"synced": None, "plain": None, "instrumental": False}


# ============================================================================
# Widgets básicos
# ============================================================================
class IconButton(QPushButton):
    def __init__(self, icon, size, icon_size, qss, tip="", color="#ffffff", parent=None):
        super().__init__(parent)
        self._isz, self._color = icon_size, color
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(tip)
        self.setStyleSheet(qss)
        self.set_icon(icon)

    def set_icon(self, name, color=None):
        if (name, color) == getattr(self, "_cur_icon", None):
            return  # o estado chega a cada 0,4 s; evita recriar o ícone sem mudança
        self._cur_icon = (name, color)
        pm = svg_pixmap(name, color or self._color, self._isz)
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(int(pm.width() / 2), int(pm.height() / 2)))


QSS_SIDE = "QPushButton{background:#000;border:1px solid #2c2c2e;border-radius:22px}QPushButton:hover{background:#141414}"
QSS_PLAIN = "QPushButton{background:transparent;border:none;border-radius:8px}QPushButton:hover{background:rgba(255,255,255,18)}QPushButton:pressed{background:rgba(255,255,255,30)}"
QSS_PILL = ("QPushButton{background:#151515;color:#fff;border:none;border-radius:18px;padding:0 16px}"
            "QPushButton:hover{background:#232325}QPushButton:checked{background:#2c2c2e}")


def qss_play(r):
    return f"QPushButton{{background:#fff;border:none;border-radius:{r}px}}QPushButton:hover{{background:#f2f2f2}}QPushButton:pressed{{background:#d8d8d8}}"


class ElideLabel(QWidget):
    def __init__(self, px, weight, color, parent=None):
        super().__init__(parent)
        self._t = ""
        self._c = QColor(color)
        self.setFont(font(px, weight))
        self.setFixedHeight(QFontMetrics(self.font()).height() + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(20)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def setText(self, t):
        t = t or ""
        if t != self._t:
            self._t = t
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.font())
        p.setPen(self._c)
        t = QFontMetrics(self.font()).elidedText(self._t, Qt.ElideRight, self.width())
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, t)


class DragBar(QWidget):
    moved = Signal(float)
    released = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.drag = None
        self.hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def _frac(self, e):
        return max(0.0, min(1.0, e.position().x() / max(1, self.width())))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = self._frac(e); self.moved.emit(self.drag); self.update()

    def mouseMoveEvent(self, e):
        if self.drag is not None:
            self.drag = self._frac(e); self.moved.emit(self.drag); self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            f = self._frac(e); self.drag = None; self.value = f
            self.released.emit(f); self.update()

    def enterEvent(self, e):
        self.hover = True; self.update()

    def leaveEvent(self, e):
        self.hover = False; self.update()

    def shown(self):
        return self.drag if self.drag is not None else self.value

    def set_value(self, v):
        if self.drag is None and abs(v - self.value) > 1e-4:
            self.value = v; self.update()


class ProgressBar(DragBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.accent = QColor("#e8572a")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 9 if (self.hover or self.drag is not None) else 7
        r = QRectF(0, (self.height() - h) / 2, self.width(), h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2c2c2e"))
        p.drawRoundedRect(r, h / 2, h / 2)
        w = self.width() * self.shown()
        if w > 0.5:
            p.setBrush(self.accent)
            p.drawRoundedRect(QRectF(0, r.y(), max(w, h), h), h / 2, h / 2)


class VolumeBar(DragBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setMinimumWidth(80)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setClipPath(path)
        p.fillRect(r, QColor("#1c1c1e"))
        p.fillRect(QRectF(0, 0, self.width() * self.shown(), r.height()), QColor("#ececec"))


class Equalizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.accent = QColor("#e8572a")
        self.on = False
        self.t = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)

    def set_on(self, on):
        if on != self.on:
            self.on = on
            if on and self.isVisible():
                self.timer.start(50)
            elif not on:
                self.timer.stop()
            self.update()

    def showEvent(self, e):
        if self.on:
            self.timer.start(50)

    def hideEvent(self, e):
        self.timer.stop()

    def _step(self):
        self.t += 0.05
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.accent)
        for i in range(3):
            h = 4 + (12 * (0.5 + 0.5 * math.sin(self.t * 6.3 + i * 2.1)) if self.on else 0)
            p.drawRoundedRect(QRectF(3 + i * 5, (18 - h) / 2, 3, h), 1.5, 1.5)


class Cover(QWidget):
    def __init__(self, size, radius, parent=None):
        super().__init__(parent)
        self.size_, self.radius = size, radius
        self.setFixedSize(size, size)
        self.pm = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_image(self, img: QImage | None):
        self.pm = rounded_pixmap(img, self.size_, self.radius) if img is not None and not img.isNull() else None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.pm:
            p.drawPixmap(0, 0, self.pm)
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1c1c1e"))
        p.drawRoundedRect(QRectF(0, 0, self.size_, self.size_), self.radius, self.radius)
        icon = svg_pixmap("note", "#48484a", max(12, self.size_ // 3))
        iw, ih = icon.width() / 2, icon.height() / 2
        p.drawPixmap(int((self.size_ - iw) / 2), int((self.size_ - ih) / 2), icon)


# ============================================================================
# Letra e fila
# ============================================================================
class LineLabel(QLabel):
    def __init__(self, text, on_click=None):
        super().__init__(text or "♪")
        self.on_click = on_click
        self.setWordWrap(True)
        self.setFont(font(19, QFont.Bold))
        self.state = None
        self.set_state("future")
        if on_click:
            self.setCursor(Qt.PointingHandCursor)

    def set_state(self, s):
        if s != self.state:
            self.state = s
            color = {"active": "#ffffff", "past": "#6e6e73", "future": "#5a5a5e", "plain": "#c7c7cc"}[s]
            self.setStyleSheet(f"color:{color};background:transparent;padding:4px 0")

    def mousePressEvent(self, e):
        if self.on_click:
            self.on_click()


class Card(QFrame):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#121212"))
        p.drawRoundedRect(QRectF(self.rect()), 20, 20)


SCROLL_QSS = ("QScrollArea{background:transparent;border:none}"
              "QScrollBar:vertical{background:transparent;width:10px;margin:14px 4px 14px 0}"
              "QScrollBar::handle:vertical{background:#3a3a3c;border-radius:3px;min-height:30px}"
              "QScrollBar::add-line,QScrollBar::sub-line{height:0}"
              "QScrollBar::add-page,QScrollBar::sub-page{background:none}")


class LyricsView(Card):
    seek = Signal(float)
    offset_step = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(250)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet(SCROLL_QSS)
        self.area.viewport().setAutoFillBackground(False)
        self.inner = QWidget()
        self.inner.setStyleSheet("background:transparent")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(22, 16, 22, 140)
        self.lay.setSpacing(2)
        self.lay.addStretch()
        self.area.setWidget(self.inner)
        v.addWidget(self.area, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(18, 6, 18, 12)
        ic = QLabel(); ic.setPixmap(svg_pixmap("sync", "#8e8e93", 17)); ic.setStyleSheet("background:transparent")
        lb = QLabel("Sincronização"); lb.setFont(font(13)); lb.setStyleSheet("color:#8e8e93;background:transparent")
        bar.addWidget(ic); bar.addSpacing(6); bar.addWidget(lb); bar.addStretch()
        self.minus = QPushButton("−"); self.plus = QPushButton("+")
        for b in (self.minus, self.plus):
            b.setFixedSize(26, 26); b.setFont(font(19)); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("QPushButton{color:#c7c7cc;background:transparent;border:none}QPushButton:hover{color:#fff}")
        self.offv = QLabel("+0,00"); self.offv.setFont(font(14)); self.offv.setFixedWidth(52)
        self.offv.setAlignment(Qt.AlignCenter); self.offv.setStyleSheet("color:#e5e5ea;background:transparent")
        bar.addWidget(self.minus); bar.addWidget(self.offv); bar.addWidget(self.plus)
        v.addLayout(bar)
        self.minus.clicked.connect(lambda: self.offset_step.emit(-0.25))
        self.plus.clicked.connect(lambda: self.offset_step.emit(0.25))

        self.lines: list[LineLabel] = []
        self.synced = None
        self.active = -2
        self.user_until = 0.0
        self.anim = QPropertyAnimation(self.area.verticalScrollBar(), b"value", self)
        self.anim.setDuration(380)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.area.viewport().installEventFilter(self)

    def eventFilter(self, o, e):
        if e.type() == QEvent.Wheel:
            self.user_until = time.monotonic() + 3.5
        return False

    def show_offset(self, o):
        self.offv.setText(("+" if o >= 0 else "−") + f"{abs(o):.2f}".replace(".", ","))

    def _clear(self):
        while self.lay.count() > 1:
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.lines, self.synced, self.active = [], None, -2
        self.area.verticalScrollBar().setValue(0)

    def message(self, text):
        self._clear()
        l = QLabel(text); l.setFont(font(15)); l.setAlignment(Qt.AlignCenter); l.setWordWrap(True)
        l.setStyleSheet("color:#8e8e93;background:transparent;padding-top:60px")
        self.lay.insertWidget(0, l)

    def set_lyrics(self, data, offset_fn):
        self._clear()
        if not data:
            self.message("Buscando letra…"); return
        if data.get("error"):
            self.message("Não foi possível buscar a letra agora."); return
        if data.get("instrumental"):
            self.message("♪  Instrumental  ♪"); return
        if data.get("synced"):
            self.synced = data["synced"]
            for i, (t, text) in enumerate(self.synced):
                lab = LineLabel(text, on_click=(lambda t=t: self.seek.emit(max(0.0, t - offset_fn() + 0.05))))
                self.lay.insertWidget(i, lab)
                self.lines.append(lab)
        elif data.get("plain"):
            for i, text in enumerate(data["plain"].splitlines()):
                lab = LineLabel(text or " ")
                lab.set_state("plain"); lab.setFont(font(16, QFont.DemiBold))
                self.lay.insertWidget(i, lab)
                self.lines.append(lab)
        else:
            self.message("Letra não encontrada para esta música.")

    def sync(self, t, force=False):
        if not self.synced:
            return
        idx = -1
        for i, (lt, _) in enumerate(self.synced):
            if lt <= t:
                idx = i
            else:
                break
        if idx == self.active and not force:
            return
        self.active = idx
        for i, lab in enumerate(self.lines):
            lab.set_state("active" if i == idx else ("past" if i < idx else "future"))
        if time.monotonic() > self.user_until and self.lines:
            target = self.lines[max(0, idx)]
            QTimer.singleShot(0, lambda: self._scroll_to(target))

    def _scroll_to(self, lab):
        try:
            self.lay.activate()  # letra recém-inserida ainda não tem geometria (y=0) sem isso
            y = max(0, lab.y() - 56)
        except RuntimeError:
            return
        self.anim.stop()
        self.anim.setStartValue(self.area.verticalScrollBar().value())
        self.anim.setEndValue(y)
        self.anim.start()


class QueueView(Card):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(230)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        h = QLabel("A seguir"); h.setFont(font(15, QFont.Bold)); h.setStyleSheet("color:#fff;background:transparent")
        v.addWidget(h)
        v.addStretch()
        m = QLabel("Nenhuma música a seguir"); m.setFont(font(15)); m.setAlignment(Qt.AlignCenter)
        m.setStyleSheet("color:#8e8e93;background:transparent")
        s = QLabel("O Windows não informa a fila do Spotify — abra o app para vê-la.")
        s.setFont(font(12)); s.setAlignment(Qt.AlignCenter); s.setWordWrap(True)
        s.setStyleSheet("color:#636366;background:transparent")
        v.addWidget(m); v.addSpacing(4); v.addWidget(s)
        b = QPushButton("Abrir reprodutor"); b.setFont(font(13, QFont.DemiBold))
        b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
        b.setStyleSheet("QPushButton{color:#fff;background:#1e1e20;border:none;border-radius:15px;padding:7px 16px}QPushButton:hover{background:#2c2c2e}")
        b.clicked.connect(open_spotify)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(b); row.addStretch()
        v.addSpacing(12); v.addLayout(row)
        v.addStretch()


# ============================================================================
# Painel completo
# ============================================================================
class PanelFrame(QFrame):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, 32, 32)


class PlayerPanel(QWidget):
    M = 60      # margem lateral para os botões redondos
    FW = 560    # largura do painel

    def __init__(self, ctl):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)
        self.view = None
        self.anchor = None  # (x_centro, y_base)

        self.frame = PanelFrame(self)
        self.frame.setFixedWidth(self.FW)
        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(0, 20, 0, 22)
        lay.setSpacing(0)

        # Cabeçalho
        head = QHBoxLayout()
        t = QLabel("Reproduzindo agora"); t.setFont(font(17, QFont.Bold)); t.setStyleSheet("color:#fff")
        self.more = IconButton("more", 38, 22, QSS_PLAIN, "Mais opções", "#d1d1d6")
        head.setContentsMargins(26, 0, 20, 0)
        head.addWidget(t); head.addStretch(); head.addWidget(self.more)
        lay.addLayout(head)

        # Vazio
        self.empty = QLabel("Nada tocando no Spotify agora.")
        self.empty.setFont(font(15)); self.empty.setStyleSheet("color:#8e8e93"); self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setMinimumHeight(130)
        lay.addWidget(self.empty)

        # Topo: capa + infos
        self.main = QWidget()
        mv = QVBoxLayout(self.main); mv.setContentsMargins(26, 14, 26, 0); mv.setSpacing(0)
        top = QHBoxLayout(); top.setSpacing(22)
        self.cover = Cover(136, 20)
        self.glow = QGraphicsDropShadowEffect(self.cover)
        self.glow.setBlurRadius(56); self.glow.setOffset(0, 0); self.glow.setColor(QColor(232, 87, 42, 200))
        self.cover.setGraphicsEffect(self.glow)
        top.addWidget(self.cover, 0, Qt.AlignVCenter)
        meta = QVBoxLayout(); meta.setSpacing(0)
        trow = QHBoxLayout(); trow.setSpacing(10)
        self.title = ElideLabel(22, QFont.Bold, "#ffffff")
        self.eq = Equalizer()
        trow.addWidget(self.title, 1); trow.addWidget(self.eq, 0, Qt.AlignVCenter)
        self.artist = ElideLabel(15, QFont.Normal, "#8e8e93")
        meta.addLayout(trow); meta.addSpacing(2); meta.addWidget(self.artist); meta.addSpacing(12)
        self.prog = ProgressBar()
        meta.addWidget(self.prog)
        times = QHBoxLayout()
        self.cur = QLabel("0:00"); self.rem = QLabel("-0:00")
        for l in (self.cur, self.rem):
            l.setFont(font(12)); l.setStyleSheet("color:#8e8e93")
        times.addWidget(self.cur); times.addStretch(); times.addWidget(self.rem)
        meta.addLayout(times); meta.addSpacing(6)
        ctr = QHBoxLayout(); ctr.setSpacing(30)
        self.bprev = IconButton("prev", 40, 28, QSS_PLAIN, "Anterior", "#e5e5ea")
        self.bpp = IconButton("pause", 50, 22, qss_play(25), "Tocar/Pausar", "#000000")
        self.bnext = IconButton("next", 40, 28, QSS_PLAIN, "Próxima", "#e5e5ea")
        ctr.addStretch(); ctr.addWidget(self.bprev); ctr.addWidget(self.bpp); ctr.addWidget(self.bnext); ctr.addStretch()
        meta.addLayout(ctr)
        top.addLayout(meta, 1)
        mv.addLayout(top)

        self.lyrics = LyricsView(); self.queue = QueueView()
        self.lyrics.hide(); self.queue.hide()
        mv.addSpacing(16)
        self.extra_gap = mv.itemAt(mv.count() - 1)
        mv.addWidget(self.lyrics); mv.addWidget(self.queue)
        mv.addSpacing(16)

        bottom = QHBoxLayout(); bottom.setSpacing(12)
        self.bvol = IconButton("vol", 30, 22, QSS_PLAIN, "Silenciar", "#e5e5ea")
        self.vbar = VolumeBar()
        self.vbar.setToolTip("Volume do Spotify no mixer do Windows\n(não é o controle de volume de dentro do Spotify)")
        self.bdev = IconButton("device", 46, 22, QSS_PLAIN, "Saída de áudio", "#8e8e93")
        self.bdev.setFixedSize(54, 34)
        self.pl = QPushButton("  Letra"); self.pq = QPushButton("  A seguir")
        for b, ic in ((self.pl, "lyrics"), (self.pq, "queue")):
            b.setIcon(QIcon(svg_pixmap(ic, "#ffffff", 18))); b.setIconSize(QSize(18, 18))
            b.setFont(font(14, QFont.Bold)); b.setFixedHeight(36); b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus); b.setStyleSheet(QSS_PILL)
        bottom.addWidget(self.bvol); bottom.addWidget(self.vbar, 1); bottom.addWidget(self.bdev)
        bottom.addWidget(self.pl); bottom.addWidget(self.pq)
        mv.addLayout(bottom)
        lay.addWidget(self.main)

        # Botões laterais
        self.s_grid = IconButton("grid", 44, 22, QSS_SIDE, "Abrir Spotify", parent=self)
        self.s_timer = IconButton("timer", 44, 22, QSS_SIDE, "Timer para pausar", parent=self)
        self.s_gear = IconButton("gear", 44, 22, QSS_SIDE, "Configurações", parent=self)
        self.s_vol = IconButton("vol", 44, 22, QSS_SIDE, "Silenciar", parent=self)
        self.badge = QLabel(self); self.badge.setFont(font(10, QFont.ExtraBold)); self.badge.hide()

        # Ligações
        self.bprev.clicked.connect(lambda: ctl.cmd("prev"))
        self.bnext.clicked.connect(lambda: ctl.cmd("next"))
        self.bpp.clicked.connect(lambda: ctl.cmd("playpause"))
        self.prog.released.connect(ctl.seek_frac)
        self.prog.moved.connect(lambda f: ctl.tick())
        self.vbar.moved.connect(ctl.volume_drag)
        self.vbar.released.connect(ctl.volume_set)
        self.bvol.clicked.connect(ctl.toggle_mute)
        self.s_vol.clicked.connect(ctl.toggle_mute)
        self.s_grid.clicked.connect(open_spotify)
        self.s_timer.clicked.connect(lambda: ctl.timer_menu(self.s_timer))
        self.s_gear.clicked.connect(lambda: ctl.settings_menu(self.s_gear.mapToGlobal(QPoint(0, 50))))
        self.more.clicked.connect(lambda: ctl.more_menu(self.more))
        self.bdev.clicked.connect(lambda: ctl.device_menu(self.bdev))
        self.pl.clicked.connect(lambda: self.set_view("lyrics"))
        self.pq.clicked.connect(lambda: self.set_view("queue"))
        self.lyrics.seek.connect(lambda t: ctl.seek(t))
        self.lyrics.offset_step.connect(ctl.change_offset)
        self.relayout()

    # --- layout ---
    def relayout(self):
        lay = self.frame.layout()
        lay.invalidate()
        lay.activate()
        fh = lay.totalHeightForWidth(self.FW) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        self.frame.setGeometry(self.M, 8, self.FW, fh)
        w, h = self.FW + 2 * self.M, fh + 16
        self.setFixedSize(w, h)
        x0, x1 = self.M - 52, self.M + self.FW + 8
        self.s_grid.move(x0, 8 + 56); self.s_timer.move(x0, 8 + 110)
        self.s_gear.move(x1, 8 + 56); self.s_vol.move(x1, 8 + 110)
        self.place()

    def place(self):
        if not self.anchor:
            return
        cx, base = self.anchor
        scr = QGuiApplication.screenAt(QPoint(cx, base - 5)) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        x = int(cx - self.width() / 2)
        x = max(g.left() + 4, min(x, g.right() - self.width() - 4))
        y = max(g.top() + 4, base - self.height() - 6)
        self.move(x, y)

    def hit_rect_contains(self, gpos: QPoint) -> bool:
        if self.frame.geometry().translated(self.pos()).adjusted(-2, -2, 2, 2).contains(gpos):
            return True
        for b in (self.s_grid, self.s_timer, self.s_gear, self.s_vol):
            if b.geometry().translated(self.pos()).contains(gpos):
                return True
        return False

    def set_view(self, v):
        self.view = None if self.view == v else v
        self.pl.setChecked(self.view == "lyrics")
        self.pq.setChecked(self.view == "queue")
        self.lyrics.setVisible(self.view == "lyrics")
        self.queue.setVisible(self.view == "queue")
        if self.view == "lyrics":
            self.ctl.ensure_lyrics()
        QTimer.singleShot(0, self.relayout)

    def set_accent(self, c: QColor):
        self.prog.accent = c; self.prog.update()
        self.eq.accent = c; self.eq.update()
        g = QColor(c); g.setAlpha(200); self.glow.setColor(g)
        self.badge.setStyleSheet(f"background:{c.name()};color:#000;border-radius:7px;padding:0 5px")

    def set_timer_badge(self, text):
        if text:
            self.badge.setText(text); self.badge.adjustSize()
            r = self.s_timer.geometry()
            self.badge.move(r.center().x() - self.badge.width() // 2, r.bottom() - 6)
            self.badge.show(); self.badge.raise_()
        else:
            self.badge.hide()

    def update_state(self, st, vol):
        has = st is not None
        self.empty.setVisible(not has)
        self.main.setVisible(has)
        if has:
            self.title.setText(st["title"] or "—")
            self.artist.setText(st["artist"])
            self.eq.set_on(st["playing"])
            self.bpp.set_icon("pause" if st["playing"] else "play")
        if vol is not None:
            v, mute = vol
            self.vbar.set_value(v)
            ic = "mute" if (mute or v == 0) else "vol"
            self.bvol.set_icon(ic); self.s_vol.set_icon(ic)
            self.vbar.setEnabled(True)
        else:
            self.vbar.set_value(0)

    def tick(self, st, pos):
        if not st:
            return
        d = st["duration"] or 0
        if self.prog.drag is not None and d:
            pos = self.prog.drag * d
        else:
            self.prog.set_value(pos / d if d else 0)
        self.cur.setText(fmt_time(pos))
        self.rem.setText("-" + fmt_time(d - pos))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.ctl.hide_panel()

    def event(self, e):
        if e.type() == QEvent.WindowDeactivate:
            QTimer.singleShot(120, self.ctl.maybe_hide_panel)
        return super().event(e)


# ============================================================================
# Mini player da barra de tarefas
# ============================================================================
class MiniBar(QWidget):
    W = 320

    def __init__(self, ctl):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME + " — mini")
        self.hover = False
        self.accent = QColor("#e8572a")
        self.progress = 0.0
        self.press = None
        self.dragging = False

        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 8, 5)
        h.setSpacing(10)
        self.cover = Cover(32, 6)
        h.addWidget(self.cover, 0, Qt.AlignVCenter)
        tv = QVBoxLayout(); tv.setSpacing(0); tv.setContentsMargins(0, 0, 0, 0)
        self.title = ElideLabel(13, QFont.DemiBold, "#ffffff")
        self.artist = ElideLabel(11, QFont.Normal, "#b4b4b8")
        tv.addStretch(); tv.addWidget(self.title); tv.addWidget(self.artist); tv.addStretch()
        h.addLayout(tv, 1)
        self.bprev = IconButton("prev", 28, 15, QSS_PLAIN, "Anterior")
        self.bpp = IconButton("pause", 30, 13, qss_play(15), "Tocar/Pausar", "#000000")
        self.bnext = IconButton("next", 28, 15, QSS_PLAIN, "Próxima")
        h.addWidget(self.bprev); h.addWidget(self.bpp); h.addWidget(self.bnext)
        self.bprev.clicked.connect(lambda: ctl.cmd("prev"))
        self.bnext.clicked.connect(lambda: ctl.cmd("next"))
        self.bpp.clicked.connect(lambda: ctl.cmd("playpause"))

    def update_state(self, st):
        if not st:
            return
        self.title.setText(st["title"] or "—")
        self.artist.setText(st["artist"])
        self.bpp.set_icon("pause" if st["playing"] else "play")
        self.setToolTip(f"{st['title']} — {st['artist']}")

    def set_progress(self, f):
        f = max(0.0, min(1.0, f))
        if abs(f - self.progress) > 0.002:
            self.progress = f
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        # alpha mínimo garante que o clique "pegue" em toda a área
        p.setBrush(QColor(255, 255, 255, 22 if self.hover else 2))
        p.drawRoundedRect(r, 7, 7)
        # linha de progresso
        y = self.height() - 3
        x0, x1 = 10.0, self.width() - 10.0
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, 2), 1, 1)
        p.setBrush(self.accent)
        p.drawRoundedRect(QRectF(x0, y, (x1 - x0) * self.progress, 2), 1, 1)

    def enterEvent(self, e):
        self.hover = True; self.update()

    def leaveEvent(self, e):
        self.hover = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press = (e.globalPosition().toPoint(), self.pos())
            self.dragging = False

    def mouseMoveEvent(self, e):
        if not self.press:
            return
        gp = e.globalPosition().toPoint()
        dx = gp.x() - self.press[0].x()
        if not self.dragging and abs(dx) > 6:
            self.dragging = True
            self.ctl.hide_panel()
        if self.dragging:
            self.move(self.press[1].x() + dx, self.press[1].y())

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.press:
            return
        if self.dragging:
            self.ctl.save_mini_position(self.x())
        else:
            self.ctl.toggle_panel()
        self.press, self.dragging = None, False

    def wheelEvent(self, e):
        self.ctl.volume_wheel(1 if e.angleDelta().y() > 0 else -1)

    def contextMenuEvent(self, e):
        self.ctl.settings_menu(e.globalPos())


# ============================================================================
# Controlador
# ============================================================================
class Controller(QObject):
    lyrics_ready = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.st = None
        self.ever_played = False
        self.audio = Audio()
        self.taskbar = Taskbar()
        self.vol = None
        self.vol_drag_t = 0.0
        self.accent = QColor("#e8572a")
        self.cover_img = None
        self.lyrics = None
        self.lyrics_key = ""
        self.timer_end = None
        self.sleep = QTimer(self); self.sleep.setSingleShot(True); self.sleep.timeout.connect(self._sleep_fire)
        self.panel_hidden_at = 0.0
        self.mouse_was_down = False

        self.mini = MiniBar(self)
        self.panel = PlayerPanel(self)
        self.lyrics_ready.connect(self._on_lyrics)

        self.worker = DemoWorker(self.cfg) if DEMO else MediaWorker(self.cfg)
        self.worker.state.connect(self._on_state)
        self.worker.thumb.connect(self._on_thumb)
        self.worker.start()

        self.t_tick = QTimer(self); self.t_tick.timeout.connect(self.tick); self.t_tick.start(100)
        self.t_bar = QTimer(self); self.t_bar.timeout.connect(self._bar_step); self.t_bar.start(250)
        self.t_vol = QTimer(self); self.t_vol.timeout.connect(self._poll_volume); self.t_vol.start(1500)
        self._bar_n = 0
        self._apply_accent_mode()

    # ---------------- estado ----------------
    def pos(self):
        st = self.st
        if not st:
            return 0.0
        p = st["position"] + ((time.monotonic() - st["_t"]) if st["playing"] else 0)
        return min(p, st["duration"]) if st["duration"] else p

    def _on_state(self, st):
        prev_key = self.st["key"] if self.st else None
        self.st = st
        if st is None:
            self.ever_played = False
        elif st["playing"]:
            self.ever_played = True
        if st and st["key"] != prev_key:
            self.lyrics = None
            if self.panel.view == "lyrics":
                self.ensure_lyrics()
            self.cover_img = None
            pt = getattr(self, "_pending_thumb", None)
            if pt and pt[1] == st["key"]:
                QTimer.singleShot(0, lambda d=pt[0], k=pt[1]: self._on_thumb(d, k))
        self.mini.update_state(st)
        self.panel.update_state(st, self.vol)
        self._update_visibility()

    def _on_thumb(self, data: bytes, key: str):
        self._pending_thumb = (data, key)
        if not self.st or key != self.st["key"]:
            return
        img = QImage.fromData(data)
        if img.isNull():
            return
        self.cover_img = img
        self.mini.cover.set_image(img)
        self.panel.cover.set_image(img)
        if self.cfg["accent_mode"] == "cover":
            self._set_accent(accent_from_image(img))

    def _set_accent(self, c: QColor):
        self.accent = c
        self.mini.accent = c; self.mini.update()
        self.panel.set_accent(c)

    def _apply_accent_mode(self):
        m = self.cfg["accent_mode"]
        if m == "orange":
            self._set_accent(QColor("#e8572a"))
        elif m == "green":
            self._set_accent(QColor("#1ed760"))
        elif self.cover_img is not None:
            self._set_accent(accent_from_image(self.cover_img))
        else:
            self._set_accent(QColor("#e8572a"))

    def tick(self):
        if not self.st:
            return
        p = self.pos()
        d = self.st["duration"] or 0
        if self.mini.isVisible():
            self.mini.set_progress(p / d if d else 0)
        if self.panel.isVisible():
            self.panel.tick(self.st, p)
            if self.panel.view == "lyrics":
                self.panel.lyrics.sync(p + self.offset())
            if self.timer_end:
                left = max(0, self.timer_end - time.monotonic())
                self.panel.set_timer_badge(f"{math.ceil(left / 60)}m")

    # ---------------- comandos ----------------
    def cmd(self, name, arg=None):
        self.worker.cmd(name, arg)

    def seek(self, t):
        self.worker.cmd("seek", t)
        if self.st:
            self.st["position"], self.st["_t"] = float(t), time.monotonic()
            self.panel.lyrics.user_until = 0
            self.tick()

    def seek_frac(self, f):
        if self.st and self.st["duration"]:
            self.seek(f * self.st["duration"])

    def _poll_volume(self):
        if self.panel.isVisible() and self.panel.vbar.drag is None:
            self.vol = self.audio.get()
            self.panel.update_state(self.st, self.vol)

    def volume_drag(self, f):
        now = time.monotonic()
        if now - self.vol_drag_t > 0.06:
            self.vol_drag_t = now
            self.audio.set(f)

    def volume_set(self, f):
        self.audio.set(f)
        self.vol = (f, f == 0)
        self.panel.update_state(self.st, self.vol)

    def volume_wheel(self, direction):
        cur = self.audio.get()
        if cur is None:
            return
        self.volume_set(max(0.0, min(1.0, cur[0] + 0.05 * direction)))

    def toggle_mute(self):
        self.audio.toggle_mute()
        self.vol = self.audio.get()
        self.panel.update_state(self.st, self.vol)

    # ---------------- letra ----------------
    def offset(self):
        return float(self.cfg["offsets"].get(self.st["key"], 0)) if self.st else 0.0

    def change_offset(self, delta):
        if not self.st:
            return
        k = self.st["key"]
        v = round(self.offset() + delta, 2)
        if v == 0:
            self.cfg["offsets"].pop(k, None)
        else:
            self.cfg["offsets"][k] = v
        while len(self.cfg["offsets"]) > 300:
            self.cfg["offsets"].pop(next(iter(self.cfg["offsets"])))
        self.cfg.save()
        self.panel.lyrics.show_offset(v)
        self.panel.lyrics.sync(self.pos() + v, force=True)

    def ensure_lyrics(self):
        if not self.st:
            return
        key = self.st["key"]
        self.panel.lyrics.show_offset(self.offset())
        if self.lyrics is not None and self.lyrics_key == key:
            return
        self.lyrics_key = key
        self.lyrics = None
        self.panel.lyrics.set_lyrics(None, self.offset)
        st = dict(self.st)

        def work():
            try:
                data = fetch_lyrics(st["title"], st["artist"], st["album"], st["duration"])
            except Exception as e:
                print("letra:", e)
                data = {"error": True}
            self.lyrics_ready.emit(key, data)

        threading.Thread(target=work, daemon=True).start()

    def _on_lyrics(self, key, data):
        if key != self.lyrics_key:
            return
        # falha de rede não fica em cache: reabrir a aba "Letra" tenta de novo
        self.lyrics = None if data.get("error") else data
        self.panel.lyrics.set_lyrics(data, self.offset)
        self.panel.lyrics.sync(self.pos() + self.offset(), force=True)

    # ---------------- visibilidade e posição ----------------
    def _update_visibility(self):
        st = self.st
        want = bool(st) and (self.ever_played or st["playing"])
        if st and not st["playing"] and self.cfg["hide_on_pause"]:
            want = False
        info = self.taskbar.info()
        if info["hidden"] or info["fullscreen"]:
            want = False
        if want and not self.mini.isVisible():
            self._place_mini(info)
            self.mini.show()
            self.taskbar.keep_on_top(self.mini)
        elif not want and self.mini.isVisible():
            self.mini.hide()
            self.hide_panel()

    def _place_mini(self, info=None):
        if self.mini.dragging:
            return
        info = info or self.taskbar.info()
        tb = info["tb"]
        h = max(30, min(tb.height() - 8, 44))
        y = tb.top() + (tb.height() - h) // 2
        w = MiniBar.W
        if self.cfg["manual_offset"] is not None:
            x = tb.center().x() + int(self.cfg["manual_offset"])
        elif info["icons_right"]:
            x = info["icons_right"] + 14
        else:
            x = tb.center().x() + 250
        right_limit = info["tray_left"] - 10
        if x + w > right_limit:
            w = max(220, right_limit - x)
            if x + w > right_limit:
                x = right_limit - w
        x = max(tb.left() + 4, x)
        if self.mini.geometry() != QRect(x, y, w, h):
            self.mini.setGeometry(x, y, w, h)

    def _bar_step(self):
        self._bar_n += 1
        if self._bar_n % 4 == 0:
            self._update_visibility()
            if self.mini.isVisible():
                self._place_mini()
        # com um menu aberto, não reerguer mini/painel: eles passariam por cima do menu
        popup = QApplication.activePopupWidget() is not None
        if self.mini.isVisible() and not popup:
            self.taskbar.keep_on_top(self.mini)
        if self.panel.isVisible():
            if not popup:
                self.taskbar.keep_on_top(self.panel)
            self._check_outside_click()

    def save_mini_position(self, x):
        tb = self.taskbar.info()["tb"]
        self.cfg["manual_offset"] = x - tb.center().x()
        self.cfg.save()

    # ---------------- painel ----------------
    def toggle_panel(self):
        if self.panel.isVisible():
            self.hide_panel()
            return
        if time.monotonic() - self.panel_hidden_at < 0.25:
            return
        g = self.mini.geometry()
        tb = self.taskbar.info()["tb"]
        self.panel.anchor = (g.center().x(), tb.top())
        self.vol = self.audio.get()
        self.panel.update_state(self.st, self.vol)
        self.panel.relayout()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self.mouse_was_down = True
        self.tick()

    def hide_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
            self.panel_hidden_at = time.monotonic()

    def maybe_hide_panel(self):
        if not self.panel.isVisible() or QApplication.activePopupWidget():
            return
        if self.panel.isActiveWindow():
            return
        if self.mini.geometry().contains(QCursor.pos()):
            return  # o clique no mini já alterna o painel
        self.hide_panel()

    def _check_outside_click(self):
        """Fecha o painel ao clicar fora (independe de foco)."""
        if not IS_WIN:
            return
        u = ctypes.windll.user32
        down = bool(u.GetAsyncKeyState(0x01) & 0x8000) or bool(u.GetAsyncKeyState(0x02) & 0x8000)
        if down and not self.mouse_was_down and not QApplication.activePopupWidget():
            gp = QCursor.pos()
            if not self.panel.hit_rect_contains(gp) and not self.mini.geometry().contains(gp):
                self.hide_panel()
        self.mouse_was_down = down

    # ---------------- menus ----------------
    def more_menu(self, btn):
        m = make_menu(self.panel)
        st = self.st or {}
        if st.get("shuffle") is not None:
            menu_item(m, "Aleatório", lambda: self.cmd("shuffle", not st.get("shuffle")), bool(st.get("shuffle")))
        if st.get("repeat") is not None:
            names = {0: "Repetir: desligado", 2: "Repetir: playlist", 1: "Repetir: música"}
            nxt = {0: 2, 2: 1, 1: 0}[st["repeat"] if st["repeat"] in (0, 1, 2) else 0]
            menu_item(m, names.get(st["repeat"], "Repetir"), lambda: self.cmd("repeat", nxt), st["repeat"] != 0)
        if not m.isEmpty():
            m.addSeparator()
        menu_item(m, "Abrir Spotify", open_spotify)
        menu_item(m, "Fechar painel", self.hide_panel)
        m.exec(btn.mapToGlobal(QPoint(btn.width() - 230, btn.height() + 4)))

    def timer_menu(self, btn):
        m = make_menu(self.panel)
        a = m.addAction("Pausar a música em"); a.setEnabled(False)
        for mins in (15, 30, 45, 60, 90):
            menu_item(m, f"{mins} minutos", lambda _=False, x=mins: self.set_timer(x * 60),
                      bool(self.timer_end and getattr(self, "_timer_mins", None) == mins))
        if self.st and self.st["duration"]:
            menu_item(m, "Fim desta música", lambda: self.set_timer(max(1, self.st["duration"] - self.pos() - 0.5), "fim"), False)
        if self.timer_end:
            m.addSeparator()
            menu_item(m, "Cancelar timer", lambda: self.set_timer(0))
        m.exec(btn.mapToGlobal(QPoint(0, btn.height() + 6)))

    def set_timer(self, seconds, tag=None):
        self.sleep.stop()
        if seconds <= 0:
            self.timer_end = None
            self._timer_mins = None
            self.panel.set_timer_badge("")
            return
        self._timer_mins = None if tag else int(seconds // 60)
        self.timer_end = time.monotonic() + seconds
        self.sleep.start(int(seconds * 1000))
        self.tick()

    def _sleep_fire(self):
        self.timer_end = None
        self.panel.set_timer_badge("")
        if self.st and self.st["playing"]:
            self.cmd("pause")

    def device_menu(self, btn):
        m = make_menu(self.panel)
        devs, default = self.audio.devices()
        if not devs:
            a = m.addAction("Nenhum dispositivo encontrado"); a.setEnabled(False)
        for did, name in devs:
            menu_item(m, name, lambda _=False, d=did: self.audio.set_default(d), did == default)
        m.addSeparator()
        menu_item(m, "Mixer de volume", lambda: os.startfile("ms-settings:apps-volume") if IS_WIN else None)
        # o botão fica na base do painel, colado na barra de tarefas: abre para cima
        m.ensurePolished()
        m.exec(btn.mapToGlobal(QPoint(0, -m.sizeHint().height() - 4)))

    def settings_menu(self, gpos: QPoint):
        m = make_menu(self.panel if self.panel.isVisible() else None)
        sub = make_menu(m); sub.setTitle("Cor de destaque")
        for key, name in (("cover", "Cor da capa"), ("orange", "Laranja"), ("green", "Verde Spotify")):
            menu_item(sub, name, lambda _=False, k=key: self._set_cfg("accent_mode", k), self.cfg["accent_mode"] == key)
        m.addMenu(sub)
        m.addSeparator()
        menu_item(m, "Esconder da barra quando pausar", lambda: self._set_cfg("hide_on_pause", not self.cfg["hide_on_pause"]), self.cfg["hide_on_pause"])
        menu_item(m, "Mostrar outros players (navegador…)", lambda: self._set_cfg("other_players", not self.cfg["other_players"]), self.cfg["other_players"])
        menu_item(m, "Posição automática na barra", lambda: self._set_cfg("manual_offset", None), self.cfg["manual_offset"] is None)
        if IS_WIN:
            menu_item(m, "Iniciar com o Windows", self._toggle_autostart, autostart_enabled())
        m.addSeparator()
        menu_item(m, "Sair", QApplication.quit)
        m.exec(gpos)

    def _set_cfg(self, k, v):
        self.cfg[k] = v
        self.cfg.save()
        if k == "accent_mode":
            self._apply_accent_mode()
        if k == "manual_offset":
            self._place_mini()
        self._update_visibility()

    def _toggle_autostart(self):
        set_autostart(not autostart_enabled())

    def shutdown(self):
        try:
            self.worker.stop()
            self.worker.wait(1500)
        except Exception:
            pass


# ============================================================================
# Iniciar com o Windows
# ============================================================================
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        cand = pyw[:-10] + "pythonw.exe"
        if os.path.exists(cand):
            pyw = cand
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, _autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except OSError:
                pass


# ============================================================================
# main
# ============================================================================
def check_windows_deps():
    missing = []
    for mod in ("winrt.windows.media.control", "winsdk.windows.media.control"):
        try:
            __import__(mod)
            break
        except ImportError:
            pass
    else:
        missing.append("winrt-Windows.Media.Control (e pacotes winrt)")
    try:
        import pycaw  # noqa
    except ImportError:
        missing.append("pycaw")
    return missing


def main():
    setup_log()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setFont(font(13))

    # instância única: segunda execução abre o painel da primeira
    sock = QLocalSocket()
    sock.connectToServer(APP_ID)
    if sock.waitForConnected(300):
        sock.write(b"show"); sock.flush(); sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(APP_ID)
    server = QLocalServer()
    server.listen(APP_ID)

    if IS_WIN and not DEMO:
        missing = check_windows_deps()
        if missing:
            QMessageBox.critical(None, APP_NAME, "Faltam pacotes Python:\n\n- " + "\n- ".join(missing) +
                                 "\n\nRode o instalar.bat que veio junto.")
            return 1

    ctl = Controller()

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(lambda: (c.readAll(), ctl.toggle_panel() if ctl.mini.isVisible() else open_spotify()))
            c.disconnected.connect(c.deleteLater)

    server.newConnection.connect(on_conn)
    app.aboutToQuit.connect(ctl.shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
