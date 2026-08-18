#!/usr/bin/env python3
"""mpris_bridge.py - expoe o mpv do rofi-ytm como player MPRIS2 proprio.

Registra org.mpris.MediaPlayer2.ytm no session bus (o hyprwave usa
preference=ytm,mpv,... -> bridge primeiro). Le o estado do mpv pela
conexao PERSISTENTE ao socket JSON (observe_property + eventos), sem
spawnar `mpvctl.py get` a cada tick; o titulo vem na hora do media-title
(seeding), e o yt-dlp (em background, cacheado em ~/.cache/rofi-ytm) so
completa o artista. Em falha do stream (403/stall) religa a mesma URL uma
vez. Reconecta sozinho se o mpv reiniciar (daemon --idle).

Morre sozinho se o mpv ficar muito tempo fora. pidfile /tmp/ytm_bridge.pid.
"""
import asyncio
import json
import logging
import os
import re
import signal as _signal
import sys
import time

from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.service import PropertyAccess, ServiceInterface, method, dbus_property, signal

PIDFILE = "/tmp/ytm_bridge.pid"
SOCK = os.environ.get("MPV_SOCKET", "/tmp/mpv-ytm.sock")
POS_POLL = 1.0          # unico poll restante: time-pos na conexao persistente
RECONNECT_DELAY = 1.0
RECONNECT_MAX = 120     # ~2min sem o mpv no socket -> a bridge sai
PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
BIG = 1_000_000
YDLP_TIMEOUT = 60.0
STOPPED_GRACE = 3.0     # entre faixas o mpv fica sem filename; segura o meta

BASE = os.path.dirname(os.path.abspath(__file__))
MPVCTL = os.path.join(BASE, "mpvctl.py")
YDLP = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
FIREFOX_PROFILE = os.environ.get(
    "YTM_PROFILE", os.path.expanduser("__FIREFOX_PROFILE__"))

_VIDEO_RE = re.compile(r"[?&]v=([0-9A-Za-z_-]{11})")
_LIST_RE = re.compile(r"[?&]list=([0-9A-Za-z_-]+)")
_DUR_RE = re.compile(r"\s+\(\d+:\d{1,2}\)$")


def ydlp_args(*extra):
    """Argumentos do yt-dlp com a conta/cookies/preferencias do rofi-ytm."""
    return [
        YDLP,
        "--no-warnings", "-J", "--skip-download",
        "--extractor-args", "youtube:player_client=web_music",
        "--remote-components", "ejs:github",
        "--cookies-from-browser", f"firefox:{FIREFOX_PROFILE}",
        *extra,
    ]


def art_url(vid):
    """URL padrao da thumbnail do YouTube (confiavel para ids reais)."""
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def entry_meta(entry):
    """{title, artist, art} de uma entry do yt-dlp (usa a maior thumbnail)."""
    title = entry.get("track") or entry.get("title") or ""
    artist = entry.get("artist") or entry.get("uploader") or ""
    art = ""
    best = None
    for t in entry.get("thumbnails") or []:
        w, h = t.get("width") or 0, t.get("height") or 0
        if best is None or (w * h) > best[0]:
            best = (w * h, t.get("url") or "")
    if best and best[1]:
        art = best[1]
    return {"title": title, "artist": artist, "art": art}


async def run_cmd(args, timeout):
    """Roda um comando e retorna (rc, stdout). Nao levanta.

    rc: 0 = ok; 1 = falhou; -1 = timeout; -2 = nao encontrado."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode, out.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        return -1, ""
    except OSError as e:
        _dbg(f"OSError no spawn: {e!r}")
        return -2, ""


def _dbg(msg):
    try:
        with open("/tmp/ytm_bridge_debug.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


WATERMARK = 1_000_000  # 1MB: rotaciona o debug log (append simples)


def _dbg_rotate():
    try:
        sz = os.path.getsize("/tmp/ytm_bridge_debug.log")
        if sz > WATERMARK:
            open("/tmp/ytm_bridge_debug.log", "w").close()
    except OSError:
        pass


# ------------------------------------------------------- caches (Fase 4)
# Persistencia em ~/.cache/rofi-ytm: letras (lyrics_player) e meta/flat-playlist
# (bridge) sobrevivem ao processo, evitando repetir yt-dlp -J / lrclib.
CACHE_DIR = os.path.expanduser(
    os.environ.get("YTM_CACHE_DIR", "~/.cache/rofi-ytm"))
META_CACHE_FILE = os.path.join(CACHE_DIR, "meta.json")
PL_CACHE_FILE = os.path.join(CACHE_DIR, "playlists.json")
META_TTL = 7 * 24 * 3600
PL_TTL = 24 * 3600


def _read_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_cache(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


class MediaPlayer2(ServiceInterface):
    def __init__(self):
        super().__init__(ROOT_IFACE)

    @method()
    def Raise(self):
        pass

    @method()
    def Quit(self):
        pass

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanSetFullscreen(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "mpv (YouTube Music)"

    @dbus_property(access=PropertyAccess.READ)
    def DesktopEntry(self) -> "s":
        return "mpv"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class Player(ServiceInterface):
    def __init__(self, bridge):
        super().__init__(PLAYER_IFACE)
        self.bridge = bridge

    @staticmethod
    def _tid(vid):
        # Object path D-Bus so aceita [A-Za-z0-9_]; vids do YouTube podem
        # conter '-' e '_' -> sanitiza (deterministico: mesmo vid, mesma key).
        return re.sub(r"[^A-Za-z0-9_]", "_", vid)

    def _metadata(self):
        st = self.bridge.state
        meta = self.bridge.meta
        vid = meta.get("video_id") or "unknown"
        d = {"mpris:trackid": Variant("o", f"/ytm/{self._tid(vid)}")}
        dur = int((st.get("dur") or 0) * BIG)
        d["mpris:length"] = Variant("x", max(dur, 1))
        if meta.get("art"):
            d["mpris:artUrl"] = Variant("s", meta["art"])
        title = meta.get("title") or st.get("title") or "YouTube Music"
        d["xesam:title"] = Variant("s", _DUR_RE.sub("", title))
        d["xesam:artist"] = Variant("as", [meta.get("artist") or "YouTube Music"])
        return d

    def _props(self):
        """Valores RAW (o dbus-next re-embrulha em Variant no getter)."""
        st = self.bridge.state
        alive = bool(st.get("alive"))
        paused = bool(st.get("paused"))
        # Entre faixas (STOPPED_GRACE) mantemos o status anterior: o mpv
        # fica sem filename no gap, mas a musica continua chegando.
        grace = (self.bridge._stopped_since is not None
                 and time.monotonic() - self.bridge._stopped_since
                 < STOPPED_GRACE)
        active = bool(st.get("filename")) or grace
        status = "Playing" if (active and alive and not paused) else (
            "Paused" if (active and alive) else "Stopped")
        count, pos = int(st.get("pl_count") or 0), int(st.get("pl_pos") or -1)
        can_next = alive and count > 1 and 0 <= pos < count - 1
        can_prev = alive and count > 1 and pos > 0
        return {
            "PlaybackStatus": status,
            "LoopStatus": "None",
            "Rate": 1.0,
            "Shuffle": False,
            "Metadata": self._metadata(),
            "Volume": max(0.0, min(1.0, (st.get("vol") or 0) / 130.0)),
            "Position": int((st.get("pos") or 0) * BIG),
            "MinimumRate": 1.0,
            "MaximumRate": 1.0,
            "CanGoNext": can_next,
            "CanGoPrevious": can_prev,
            "CanPlay": bool(alive),
            "CanPause": bool(alive),
            "CanSeek": bool(alive),
            "CanControl": True,
        }

    # Getters: o nome da funcao PRECISA ser o nome exato da property MPRIS
    # (o dbus-next registra a property pelo nome do metodo).
    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self._props()["PlaybackStatus"]

    @dbus_property(access=PropertyAccess.READ)
    def LoopStatus(self) -> "s":
        return self._props()["LoopStatus"]

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return self._props()["Rate"]

    @dbus_property(access=PropertyAccess.READ)
    def Shuffle(self) -> "b":
        return self._props()["Shuffle"]

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return self._props()["Metadata"]

    @dbus_property(access=PropertyAccess.READ)
    def Volume(self) -> "d":
        return self._props()["Volume"]

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return self._props()["Position"]

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return self._props()["MinimumRate"]

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return self._props()["MaximumRate"]

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return self._props()["CanGoNext"]

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return self._props()["CanGoPrevious"]

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return self._props()["CanPlay"]

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return self._props()["CanPause"]

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return self._props()["CanSeek"]

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return self._props()["CanControl"]

    async def _mpv(self, *args):
        return await run_cmd([sys.executable, MPVCTL, *args], 4.0)

    @method()
    def Play(self):
        if self.bridge.state.get("paused"):
            asyncio.ensure_future(self._mpv("toggle"))

    @method()
    def Pause(self):
        if not self.bridge.state.get("paused"):
            asyncio.ensure_future(self._mpv("toggle"))

    @method()
    def PlayPause(self):
        asyncio.ensure_future(self._mpv("toggle"))

    @method()
    def Stop(self):
        asyncio.ensure_future(self._mpv("stop"))

    @method()
    def Next(self):
        asyncio.ensure_future(self._mpv("next"))

    @method()
    def Previous(self):
        asyncio.ensure_future(self._mpv("prev"))

    @method()
    def Seek(self, offset: "x"):
        pos = (self.bridge.state.get("pos") or 0) + offset / BIG
        asyncio.ensure_future(self._mpv("seek", str(max(0.0, pos))))

    @method()
    def SetPosition(self, track_id: "o", position: "x"):
        asyncio.ensure_future(self._mpv("seek", str(max(0.0, position / BIG))))

    @method()
    def OpenUri(self, uri: "s"):
        pass

    @signal()
    def Seeked(self, position: "x"):
        pass


class Bridge:
    def __init__(self):
        self.state = {"alive": False, "title": "", "pos": 0.0, "dur": 0.0,
                      "vol": 0, "paused": False, "filename": "",
                      "pl_count": 0, "pl_pos": -1}
        self.meta = {}          # video atual: {video_id, title, artist, art}
        self.flat = {}          # list_id -> [entries do --flat-playlist]
        self._meta_cache = _read_cache(META_CACHE_FILE)
        self._pl_cache = _read_cache(PL_CACHE_FILE)
        self._known_vid = ""    # id da faixa que ja esta sendo enriquecida
        self.retried = False    # retry de stream (403/stall) - 1x por faixa
        self._pending_seek = False
        self._writer = None     # conexao persistente (para puts one-shot)
        self._stopped_since = None   # monotonic da ultima vez sem filename
        self.player = None
        self.last_props = None

    # ---------------------------------------------------------- enrichment
    def _video_id(self):
        m = _VIDEO_RE.search(self.state.get("filename") or "")
        return m.group(1) if m else ""

    def _prepare_entries(self, entries):
        out = []
        for e in entries:
            vid = _VIDEO_RE.search(e.get("url") or e.get("webpage_url") or "")
            e["_vid"] = vid.group(1) if vid else ""
            out.append(e)
        return out

    async def _playlist_video_id(self):
        """Id + entrada da faixa atual quando tocando playlist.
        --flat-playlist cacheado em disco (~/.cache/rofi-ytm/playlists.json,
        TTL 1 dia): nao reroda o yt-dlp a cada play da mesma playlist."""
        m = _LIST_RE.search(self.state.get("filename") or "")
        if not m:
            return "", {}
        lid = m.group(1)
        if lid not in self.flat:
            cached = self._pl_cache.get(lid)
            if cached and time.time() - (cached.get("ts") or 0) < PL_TTL:
                self.flat[lid] = self._prepare_entries(cached.get("entries") or [])
                _dbg(f"flat-playlist (cache) list={lid[:10]} {len(self.flat[lid])} itens")
            else:
                rc, out = await run_cmd(
                    ydlp_args("--flat-playlist", "-J",
                              f"https://music.youtube.com/playlist?list={lid}"),
                    YDLP_TIMEOUT)
                entries = []
                if rc == 0:
                    try:
                        entries = self._prepare_entries(
                            json.loads(out).get("entries") or [])
                    except ValueError:
                        entries = []
                else:
                    _dbg(f"flat-playlist falhou ({rc}) para list={lid}")
                self.flat[lid] = entries
                if entries:
                    self._pl_cache[lid] = {"entries": entries, "ts": time.time()}
                    _write_cache(PL_CACHE_FILE, self._pl_cache)
        pos = int(self.state.get("pl_pos") or -1)
        entries = self.flat[lid]
        if 0 <= pos < len(entries):
            return entries[pos].get("_vid") or "", entries[pos]
        return "", {}

    def _meta_for(self, vid, flat_entry):
        """Monta meta. Art vem do padrao i.ytimg (imediato); o titulo é
        semeado pelo media-title do mpv (que já é o titulo real extraído
        pelo próprio yt-dlp do mpv); yt-dlp -J fica só para o artista."""
        meta = {"video_id": vid, "title": "", "artist": "",
                "art": art_url(vid)}
        if flat_entry:
            meta["title"] = flat_entry.get("track") or flat_entry.get("title") or ""
            meta["artist"] = (flat_entry.get("artist")
                              or flat_entry.get("uploader") or "")
        if not meta["title"]:
            meta["title"] = self.state.get("title") or ""
        return meta

    async def _fetch_meta(self, vid, flat_entry=None):
        """Metadata imediato (seed do media-title / flat-entry) + yt-dlp -J
         em background só para o artista (faixa única), cacheado por vid."""
        cached = self._meta_cache.get(vid)
        if cached and time.time() - (cached.get("ts") or 0) < META_TTL:
            self.meta = {k: cached.get(k, "") for k in
                         ("video_id", "title", "artist", "art")}
            self.meta["video_id"] = cached.get("video_id") or vid
            self.meta["art"] = art_url(vid)   # sempre a capa da faixa
            self._emit_changes()
            return

        meta = self._meta_for(vid, flat_entry)
        self.meta = meta                      # exibe na hora (seed)
        self._emit_changes()

        if flat_entry:
            if meta["artist"]:
                self._store_meta(vid, self.meta)
            return
        if not meta["title"]:
            await self._ytdlp_meta(vid)
        elif not meta["artist"]:
            await self._ytdlp_meta(vid)
        else:
            self._store_meta(vid, self.meta)

    async def _ytdlp_meta(self, vid):
        if not vid:
            self._emit_changes()
            return
        rc, out = await run_cmd(
            ydlp_args(f"https://music.youtube.com/watch?v={vid}"),
            YDLP_TIMEOUT)
        if rc == 0:
            try:
                self.meta.update(entry_meta(json.loads(out)))
                self.meta["art"] = art_url(vid)  # capa da faixa, nao do album
                self._store_meta(vid, self.meta)
            except ValueError:
                _dbg(f"yt-dlp json invalido para {vid}")
        else:
            _dbg(f"yt-dlp falhou ({rc}) para {vid}; len(out)={len(out)}")
        self._emit_changes()

    def _store_meta(self, vid, meta):
        self._meta_cache[vid] = dict(meta)
        self._meta_cache[vid]["ts"] = time.time()
        _write_cache(META_CACHE_FILE, self._meta_cache)

    # ----------------------------------------------------------- mpv socket
    OBS = {10: "media-title", 11: "pause", 12: "volume", 13: "filename",
           14: "playlist-count", 15: "playlist-pos"}

    def _apply_prop(self, name, data):
        if name == "media-title":
            self.state["title"] = data or ""
        elif name == "pause":
            self.state["paused"] = bool(data)
        elif name == "volume":
            self.state["vol"] = int(data or 0)
        elif name == "filename":
            self.state["filename"] = data or ""
        elif name == "playlist-count":
            self.state["pl_count"] = int(data or 0)
        elif name == "playlist-pos":
            self.state["pl_pos"] = int(data or -1)
        else:
            return False
        return True

    def _sync_video(self):
        """Detecta troca de faixa (watch URL ou playlist) e enriquece,
        cuidando do seed de titulo que pode chegar apos o filename."""
        if not self.state.get("alive") or not self.state.get("filename"):
            # transicao entre faixas: o mpv fica brevemente sem filename,
            # mantemos meta/status por STOPPED_GRACE para a janela de letras
            # e o painel nao fecharem; zera de vez se realmente parou.
            now = time.monotonic()
            if self._stopped_since is None:
                self._stopped_since = now
            if now - self._stopped_since < STOPPED_GRACE:
                return
            self.meta = {}
            return
        self._stopped_since = None
        vid = self._video_id()
        if vid:
            if vid == self._known_vid and self.meta.get("title"):
                return
            if vid == self._known_vid:
                if self.state.get("title") and not self.meta.get("title"):
                    self.meta["title"] = self.state["title"]
                    self._emit_changes()
                if not self.meta.get("artist"):
                    asyncio.ensure_future(self._ytdlp_meta(vid))
                return
            self._known_vid = vid
            self.retried = False
            asyncio.ensure_future(self._fetch_meta(vid, None))
            return
        asyncio.ensure_future(self._ask_playlist_vid())

    async def _ask_playlist_vid(self):
        """Fallback de vid quando o filename do mpv nao tem watch/list URL
        (fila/stream resolvido): pede a playlist completa na conexao
        persistente e o handler do rid 52 extrai a entry atual."""
        writer = self._writer
        if writer is None:
            asyncio.ensure_future(self._playlist_sync())
            return
        try:
            await self._send(writer, [
                {"command": ["get_property", "playlist"], "request_id": 52}])
        except (ConnectionError, OSError):
            asyncio.ensure_future(self._playlist_sync())

    async def _playlist_sync(self):
        vid, flat_entry = await self._playlist_video_id()
        if vid and vid != self._known_vid:
            self._known_vid = vid
            self.retried = False
            await self._fetch_meta(vid, flat_entry)
        self._emit_changes()

    def _emit_changes(self):
        player = self.player
        if player is None:
            return
        props = player._props()
        if self.last_props is None:
            changed = {k: v for k, v in props.items() if k != "Position"}
            player.emit_properties_changed(changed, [])
        else:
            changed = {k: v for k, v in props.items()
                       if self.last_props.get(k) != v}
            if changed:
                player.emit_properties_changed(changed, [])
        self.last_props = props

    def _handle_line(self, line, player):
        try:
            msg = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return
        ev = msg.get("event")
        rid = msg.get("request_id")
        if ev == "property-change":
            name = msg.get("name")
            self._apply_prop(name, msg.get("data"))
            if name in ("filename", "playlist-pos"):
                self._sync_video()
            elif (name == "media-title" and not self.meta.get("title")
                  and self.state.get("title")):
                self._sync_video()
            self._emit_changes()
        elif ev == "start-file":
            self.retried = False
        elif ev == "end-file":
            self._on_end_file(msg)
        elif ev == "seek":
            self._pending_seek = True
        elif ev == "playback-restart":
            self._emit_changes()
        elif rid is not None:
            if rid in self.OBS and "data" in msg:   # seed get_property
                name = self.OBS[rid]
                self._apply_prop(name, msg["data"])
                if name in ("filename", "playlist-pos"):
                    self._sync_video()
                elif (name == "media-title" and not self.meta.get("title")
                      and self.state.get("title")):
                    self._sync_video()
                self._emit_changes()
            elif rid == 50:                       # poll time-pos
                self.state["pos"] = float(msg.get("data") or 0.0)
                if self._pending_seek:
                    self._pending_seek = False
                    try:
                        player.Seeked(int((self.state.get("pos") or 0) * BIG))
                    except Exception:
                        pass
                self._emit_changes()
            elif rid == 51:                     # poll duration
                self.state["dur"] = float(msg.get("data") or 0.0)
                self._emit_changes()
            elif rid == 52:                   # get playlist (fallback de vid)
                entries = msg.get("data") or []
                vid = ""
                for e in entries:
                    if e.get("current"):
                        m = _VIDEO_RE.search(e.get("filename") or "")
                        vid = m.group(1) if m else ""
                        break
                if vid and vid != self._known_vid:
                    self._known_vid = vid
                    self.retried = False
                    asyncio.ensure_future(self._fetch_meta(vid, None))
                self._emit_changes()

    def _on_end_file(self, msg):
        if msg.get("reason") != "error":
            return
        url = self.state.get("filename") or ""
        if not url or self.retried:
            return
        self.retried = True
        _dbg(f"end-file error -> religando em 2s: {url[:60]}")
        asyncio.ensure_future(self._notify(
            "Conexão do stream falhou - tentando novamente..."))
        asyncio.ensure_future(self._retry(url))

    async def _retry(self, url):
        await asyncio.sleep(2.0)
        try:
            _reader, writer = await asyncio.open_unix_connection(SOCK)
        except OSError:
            return
        cmds = [{"command": ["loadfile", url, "replace"], "request_id": 60}]
        try:
            writer.write(("".join(json.dumps(c) + "\n" for c in cmds)).encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        try:
            writer.close()
        except OSError:
            pass

    async def _notify(self, body, title="YouTube Music"):
        await run_cmd(["notify-send", "-u", "normal", "--", title, body], 5.0)

    async def _send(self, writer, cmds):
        writer.write(("".join(json.dumps(c) + "\n" for c in cmds)).encode())
        await writer.drain()

    async def _pos_poller(self, writer):
        while True:
            await asyncio.sleep(POS_POLL)
            try:
                await self._send(writer, [
                    {"command": ["get_property", "time-pos"], "request_id": 50},
                    {"command": ["get_property", "duration"], "request_id": 51}])
            except (ConnectionError, OSError):
                return

    async def _reader(self, reader, player):
        while True:
            try:
                line = await reader.readuntil(b"\n")
            except asyncio.IncompleteReadError as e:
                if e.partial:
                    self._handle_line(e.partial, player)
                return
            except (asyncio.LimitOverrunError, ConnectionError, OSError):
                return
            self._handle_line(line, player)

    async def _drive(self):
        player = self.player
        fails = 0
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(SOCK)
            except OSError:
                fails += 1
                if fails >= RECONNECT_MAX:
                    _dbg("mpv ausente por muito tempo - bridge saindo")
                    return
                await asyncio.sleep(RECONNECT_DELAY)
                continue
            fails = 0
            self._writer = writer
            # conexao nova: re-observe para re-semear o estado em props/events
            self.state["alive"] = True
            self.state["filename"] = ""
            self._known_vid = ""
            self.meta = {}
            self._stopped_since = None
            try:
                await self._send(writer, [
                    {"command": ["observe_property", i, n],
                     "request_id": i} for i, n in self.OBS.items()])
                # O observe_property NEM SEMPRE emite o valor atual no
                # property-change inicial (ex.: filename chega sem "data").
                # Seed confiavel: get_property de cada propriedade observada.
                await self._send(writer, [
                    {"command": ["get_property", n], "request_id": i}
                    for i, n in self.OBS.items()])
            except (ConnectionError, OSError):
                continue

            poller = asyncio.ensure_future(self._pos_poller(writer))
            rtask = asyncio.ensure_future(self._reader(reader, player))
            done, _ = await asyncio.wait(
                {rtask, poller}, return_when=asyncio.FIRST_COMPLETED)
            for t in (rtask, poller):
                t.cancel()
            try:
                await asyncio.gather(rtask, poller, return_exceptions=True)
            except Exception:
                pass
            try:
                writer.close()
            except OSError:
                pass
            self._writer = None
            self.state["alive"] = False
            self._emit_changes()

    # -------------------------------------------------------------- loop
    async def run(self):
        bus = await MessageBus().connect()
        bus.export(PATH, MediaPlayer2())
        player = Player(self)
        bus.export(PATH, player)
        try:
            await bus.request_name("org.mpris.MediaPlayer2.ytm")
        except Exception:
            return  # outro player com o mesmo nome (ex.: bridge duplicada)

        self.player = player
        await self._drive()


def main():
    logging.getLogger("dbus_next").setLevel(logging.CRITICAL)
    _dbg_rotate()

    def _cleanup():
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass

    def _sig(_signum, _frame):
        _cleanup()
        sys.exit(0)

    _signal.signal(_signal.SIGTERM, _sig)
    _signal.signal(_signal.SIGINT, _sig)

    if os.path.exists(PIDFILE):
        try:
            pid = int(open(PIDFILE).read().strip() or 0)
            if pid and os.kill(pid, 0) is None:
                sys.exit(0)  # ja existe uma bridge rodando
        except (ValueError, OSError, FileNotFoundError):
            pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        asyncio.run(Bridge().run())
    finally:
        _cleanup()


if __name__ == "__main__":
    main()