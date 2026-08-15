#!/usr/bin/env python3
"""mpris_bridge.py - expoe o mpv do rofi-ytm como player MPRIS2 proprio.

Registra org.mpris.MediaPlayer2.ytm no session bus (o hyprwave usa
preference=ytm,mpv,... -> bridge primeiro). Le o estado do mpv pelo
socket JSON (mpvctl.py) e enriquece com yt-dlp: titulo/artista reais e
mpris:artUrl com a thumbnail do YouTube (o hyprwave baixa a URL sozinho,
sem cache em disco).

Morre sozinho quando o mpv morre (o socket some). pidfile /tmp/ytm_bridge.pid.
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
POLL = 0.5
PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
BIG = 1_000_000
YDLP_TIMEOUT = 60.0

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
    return f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"


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

    def _metadata(self):
        st = self.bridge.state
        meta = self.bridge.meta
        vid = meta.get("video_id") or "unknown"
        d = {"mpris:trackid": Variant("o", f"/ytm/{vid}")}
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
        status = "Playing" if alive and not paused else (
            "Paused" if alive else "Stopped")
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
        self.last_props = None

    # ---------------------------------------------------------- enrichment
    def _video_id(self):
        m = _VIDEO_RE.search(self.state.get("filename") or "")
        return m.group(1) if m else ""

    async def _playlist_video_id(self):
        """Id + entrada da faixa atual quando tocando playlist
        (via --flat-playlist, cacheado em self.flat)."""
        m = _LIST_RE.search(self.state.get("filename") or "")
        if not m:
            return "", {}
        lid = m.group(1)
        if lid not in self.flat:
            rc, out = await run_cmd(
                ydlp_args("--flat-playlist", "-J",
                          f"https://music.youtube.com/playlist?list={lid}"),
                YDLP_TIMEOUT)
            entries = []
            if rc == 0:
                try:
                    entries = json.loads(out).get("entries") or []
                    for e in entries:
                        vid = _VIDEO_RE.search(
                            e.get("url") or e.get("webpage_url") or "")
                        e["_vid"] = vid.group(1) if vid else ""
                except ValueError:
                    entries = []
            else:
                _dbg(f"flat-playlist falhou ({rc}) para list={lid}")
            self.flat[lid] = entries
        pos = int(self.state.get("pl_pos") or -1)
        entries = self.flat[lid]
        if 0 <= pos < len(entries):
            return entries[pos].get("_vid") or "", entries[pos]
        return "", {}

    def _meta_for(self, vid, flat_entry):
        """Monta meta. Art vem do padrao i.ytimg (imediato); a chamada lenta
        do yt-dlp fica reservada para title/artist do caso faixa-unica."""
        meta = {"video_id": vid, "title": "", "artist": "", "art": art_url(vid)}
        if flat_entry:
            meta["title"] = flat_entry.get("track") or flat_entry.get("title") or ""
            meta["artist"] = (flat_entry.get("artist")
                              or flat_entry.get("uploader") or "")
        return meta

    async def _fetch_meta(self, vid, flat_entry=None):
        """Busca title/artist. Faixa-unica: yt-dlp -J na watch URL (lento).
        Playlist: flat-entry ja tem title (imediato, sem yt-dlp extra)."""
        meta = self._meta_for(vid, flat_entry)
        if not meta["title"]:
            rc, out = await run_cmd(
                ydlp_args(f"https://music.youtube.com/watch?v={vid}"),
                YDLP_TIMEOUT)
            if rc == 0:
                try:
                    meta.update(entry_meta(json.loads(out)))
                    if not meta.get("art"):
                        meta["art"] = art_url(vid)
                except ValueError:
                    _dbg(f"yt-dlp json invalido para {vid}")
            else:
                _dbg(f"yt-dlp falhou ({rc}) para {vid}; len(out)={len(out)}")
        self.meta = meta

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

        known_vid = ""
        dead = 0
        while True:
            rc, out = await run_cmd([sys.executable, MPVCTL, "get"], 4.0)
            try:
                st = json.loads(out) if rc == 0 else {}
            except ValueError:
                st = {}
            if not st.get("alive"):
                dead += 1
                if dead >= 2:
                    return  # mpv morreu; a bridge morre junto
                await asyncio.sleep(POLL)
                continue
            dead = 0
            self.state = st

            vid = self._video_id()
            flat_entry = {}
            if not vid:
                vid, flat_entry = await self._playlist_video_id()
            if vid and vid != known_vid:
                known_vid = vid
                asyncio.ensure_future(self._fetch_meta(vid, flat_entry))

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
            await asyncio.sleep(POLL)


def main():
    logging.getLogger("dbus_next").setLevel(logging.CRITICAL)

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