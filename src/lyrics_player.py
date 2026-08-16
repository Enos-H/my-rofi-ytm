#!/usr/bin/env python3
"""lyrics_player.py - letras sincronizadas (karaoke ANSI) para o mpv do rofi-ytm.

Consome o MPRIS da bridge (org.mpris.MediaPlayer2.ytm; fallback para o
MPRIS nativo do mpv) via dbus-next: Metadata (xesam:title/artist/
mpris:length/trackid), Position (us) e PlaybackStatus. Busca as letras no
lrclib.net (LRC com timestamps; sem sync, cai para a letra completa
distribuida pela duracao; sem nada, mensagem). Renderiza no estilo do
base.py do repo "C-DIGO-BASE-PARA-A-LYRICS", sincronizado pela posicao
real do player (nao por relogio interno).

Sai sozinho quando o player morre (status Stopped ou nome some do bus).
"""
import asyncio
import json
import os
import re
import signal as _signal
import sys
import urllib.parse
import urllib.request

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

# ------------------------------- ANSI ---------------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
INACTIVE_COLOR = "\033[38;5;239m"
HIGHLIGHT_COLOR = ""  # cor padrao do terminal para a linha ativa
INFO_COLOR = ""
CURSOR_POS = lambda row, col: f"\033[{row};{col}H"
CLEAR_SCREEN = "\033[H\033[J"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

TEXT_WIDTH = 60
TEXT_HEIGHT = 15
terminal_width = 80
terminal_height = 24

# ------------------------------ D-Bus ---------------------------------
YT_PLAYER = "org.mpris.MediaPlayer2.ytm"
MPV_PLAYER = "org.mpris.MediaPlayer2.mpv"
PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
POLL = 0.2
GONE_LIMIT = 20     # ~4s sem o player no bus -> sair (janela fecha)
BUFFER_LIMIT = 25   # ~5s sem metadata valida -> sair

LRCLIB = "https://lrclib.net/api"
UA = "rofi-ytm/1.0 (lyrics)"
MAX_FETCH = 10.0

_DUR_RE = re.compile(r"\s+\(\d+:\d{1,2}\)$")
_LRC_TAG = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_ID_RE = re.compile(r"/ytm/([0-9A-Za-z_-]{11})")

CACHE = {}           # trackid -> {"kind": lrc|plain|none|instrumental, "data": [...]}
last_drawn = -1


# -------------------------- terminal helpers --------------------------
def update_terminal_size():
    global terminal_width, terminal_height
    try:
        w, h = os.get_terminal_size()
    except OSError:
        w, h = TEXT_WIDTH + 4, TEXT_HEIGHT + 3
    try:
        terminal_width = max(20, int(os.environ.get("LYRICS_COLS", w)))
    except ValueError:
        terminal_width = max(20, w)
    try:
        terminal_height = max(10, int(os.environ.get("LYRICS_ROWS", h)))
    except ValueError:
        terminal_height = max(10, h)


def split_and_wrap_text(text, max_width):
    parts = text.split("\n")
    wrapped = []
    for part in parts:
        words = part.split()
        cur, cur_len = [], 0
        for word in words:
            if cur_len + len(word) + (1 if cur else 0) <= max_width:
                cur.append(word)
                cur_len += len(word) + (1 if cur else 0)
            else:
                if cur:
                    wrapped.append(" ".join(cur))
                cur, cur_len = [word], len(word)
        if cur:
            wrapped.append(" ".join(cur))
    return wrapped


LINE_GAP = 3   # (legado) linhas de terminal ocupadas por cada linha de letra


def display(idx, lyrics_data, title, artist, notice=""):
    """Desenha titulo/artista no topo e as letras com a linha ativa destacada.

    O layout se adapta ao tamanho real do terminal: texto quebrado por
    palavra (nunca corta no meio), linhas do mesmo verso consecutivas e
    exatamente uma linha vazia entre versos diferentes.
    """
    out = sys.stdout
    out.write(CLEAR_SCREEN)
    tw = max(20, terminal_width - 4)
    th = max(10, terminal_height - 3)
    row = 0
    for part in (title + "\n" + artist).split("\n"):
        for line in split_and_wrap_text(part, tw):
            if row < th:
                out.write(CURSOR_POS(1 + row, 2))
                out.write(f"{BOLD}{INFO_COLOR}{line}{RESET}")
                row += 1
    if notice:
        if row < th:
            row += 1
            out.write(CURSOR_POS(1 + row, 2))
            out.write(f"{INACTIVE_COLOR}{notice}{RESET}")
    else:
        row += 1
        i = max(0, idx)
        first = True
        while i < len(lyrics_data):
            lines = split_and_wrap_text(lyrics_data[i].get("original", ""), tw)
            if not lines:
                i += 1
                continue
            need = len(lines) + (0 if first else 1)
            if row + need > th:
                break
            if not first:
                row += 1
            color = BOLD + (HIGHLIGHT_COLOR or "") if i == idx else INACTIVE_COLOR
            for line in lines:
                out.write(CURSOR_POS(1 + row, 2))
                out.write(f"{color}{line}{RESET}")
                row += 1
            first = False
            i += 1
    out.write(CURSOR_POS(terminal_height - 1, 1))
    out.flush()


# ------------------------------ lrclib ---------------------------------
def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=MAX_FETCH) as r:
        return json.load(r)


def parse_lrc(text):
    out = []
    for line in text.splitlines():
        tags = _LRC_TAG.findall(line)
        if not tags:
            continue
        rest = _LRC_TAG.sub("", line).strip()
        if not rest:
            continue
        for m, s in tags:
            out.append({"time": int(m) * 60 + float(s), "original": rest})
    out.sort(key=lambda e: e["time"])
    return out


def distribute_plain(lines, dur):
    if dur <= 0:
        dur = 1.0
    n = max(1, len(lines))
    return [{"time": i * (dur / n), "original": line}
            for i, line in enumerate(lines) if line.strip()]


def fetch_lyrics(title, artist):
    """Retorna {"kind": lrc|plain|none|instrumental, "data": [...]}."""
    try:
        item = _fetch(f"{LRCLIB}/get?"
                      + urllib.parse.urlencode({"artist_name": artist,
                                                "track_name": title}))
    except Exception:
        item = None
    if not item:
        item = None
        queries = ([f"{title} {artist}".strip()] if artist else []) + [title]
        for q in queries:
            if not q:
                continue
            try:
                rows = _fetch(f"{LRCLIB}/search?"
                              + urllib.parse.urlencode({"q": q}))
            except Exception:
                rows = []
            if rows:
                item = rows[0]
                for r in rows:
                    if r.get("syncedLyrics"):
                        item = r
                        break
                break
    if not item:
        return {"kind": "none", "data": []}
    if item.get("instrumental"):
        return {"kind": "instrumental", "data": []}
    synced = item.get("syncedLyrics")
    if synced:
        return {"kind": "lrc", "data": parse_lrc(synced)}
    plain = item.get("plainLyrics")
    if plain:
        return {"kind": "plain", "data": plain.splitlines()}
    return {"kind": "none", "data": []}


def get_lyrics(tid, title, artist, dur):
    if tid in CACHE:
        return CACHE[tid]
    result = fetch_lyrics(title, artist)
    if result["kind"] == "plain":
        result["data"] = distribute_plain(result["data"], dur)
    CACHE[tid] = result
    return result


# ------------------------------ loop ----------------------------------
async def get_props(bus, owner):
    msg = Message(destination=owner, path=PATH, interface=PROPS_IFACE,
                  member="GetAll", signature="s", body=[PLAYER_IFACE])
    reply = await bus.call(msg)
    if reply.message_type != MessageType.METHOD_RETURN:
        raise RuntimeError(reply.error_name or "dbus error")
    return reply.body[0]


def read_state(props):
    md = props.get("Metadata")
    md = md.value if isinstance(md, Variant) else (md or {})
    title = artist = tid = ""
    dur = 0.0
    if isinstance(md, dict):
        t = md.get("xesam:title")
        title = str(t.value) if isinstance(t, Variant) else ""
        a = md.get("xesam:artist")
        if isinstance(a, Variant):
            artists = a.value
            artist = ", ".join(str(x) for x in artists) if isinstance(artists, list) else str(artists)
        raw_tid = md.get("mpris:trackid")
        raw_tid = str(raw_tid.value) if isinstance(raw_tid, Variant) else ""
        m = _ID_RE.search(raw_tid)
        tid = m.group(1) if m else (raw_tid.replace("/ytm/", "") or "")
        ln = md.get("mpris:length")
        if isinstance(ln, Variant) and ln.value:
            dur = float(ln.value) / 1_000_000
    p = props.get("Position")
    try:
        pos = float(p.value if isinstance(p, Variant) else p) / 1_000_000
    except (TypeError, ValueError):
        pos = 0.0
    s = props.get("PlaybackStatus")
    status = str(s.value if isinstance(s, Variant) else s or "")
    return {"trackid": tid, "title": _DUR_RE.sub("", title), "artist": artist,
            "dur": dur, "pos": pos, "status": status}


async def main_loop():
    global last_drawn
    bus = await MessageBus().connect()

    owner = YT_PLAYER
    reply = await bus.call(Message(destination="org.freedesktop.DBus",
                                   path="/org/freedesktop/DBus",
                                   interface="org.freedesktop.DBus",
                                   member="NameHasOwner", signature="s",
                                   body=[owner]))
    if not (reply.message_type == MessageType.METHOD_RETURN and
            reply.body and reply.body[0]):
        owner = MPV_PLAYER

    def cleanup(_signum=None, _frame=None):
        sys.stdout.write(CLEAR_SCREEN + SHOW_CURSOR)
        sys.stdout.flush()
        sys.exit(0)

    _signal.signal(_signal.SIGTERM, cleanup)
    _signal.signal(_signal.SIGINT, cleanup)
    sys.stdout.write(HIDE_CURSOR)

    gone = 0
    buffering = 0
    known_tid = ""
    last_drawn = -1
    prev_size = (terminal_width, terminal_height)
    update_terminal_size()
    while True:
        update_terminal_size()
        if (terminal_width, terminal_height) != prev_size:
            prev_size = (terminal_width, terminal_height)
            last_drawn = -1
        try:
            props = await get_props(bus, owner)
            gone = 0
        except Exception:
            gone += 1
            if gone >= GONE_LIMIT:
                break
            await asyncio.sleep(POLL)
            continue

        st = read_state(props)
        if st["status"] == "Stopped":
            break

        if not st["title"]:
            buffering += 1
            if buffering >= BUFFER_LIMIT:
                break
            await asyncio.sleep(POLL)
            continue
        buffering = 0

        if st["trackid"] != known_tid:
            known_tid = st["trackid"]
            last_drawn = -1

        lyrics = get_lyrics(known_tid, st["title"], st["artist"], st["dur"])
        if lyrics["kind"] in ("none", "instrumental"):
            notice = ("Faixa instrumental (sem letras)" if lyrics["kind"] == "instrumental"
                      else "Letra nao encontrada")
            if last_drawn != -2:
                display(0, [], st["title"], st["artist"], notice)
                last_drawn = -2
        else:
            data = lyrics.get("data") or []
            idx = 0
            for i, e in enumerate(data):
                if st["pos"] >= e["time"]:
                    idx = i
                else:
                    break
            if idx != last_drawn:
                display(idx, data, st["title"], st["artist"])
                last_drawn = idx
        await asyncio.sleep(POLL)

    sys.stdout.write(CLEAR_SCREEN + SHOW_CURSOR)
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(CLEAR_SCREEN + SHOW_CURSOR)
        sys.stdout.flush()