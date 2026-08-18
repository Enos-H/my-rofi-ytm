#!/usr/bin/env python3
"""mpvctl - controle do mpv (rofi-ytm) via JSON IPC. Somente stdlib.

O mpv roda como daemon persistente (--idle); as faixas sao trocadas com
`loadfile` sem matar/reiniciar o processo (painel e letras nao morrem).

Comandos:
  get              imprime JSON com title/time-pos/duration/volume/pause/
                   filename/playlist-count/playlist-pos/alive
  toggle           alterna play/pause
  stop             encerra o mpv (graceful) e remove o socket
  vol <+N|-N|N>    ajusta o volume (0-130)
  seek <segundos>  pula para a posicao (usado pelo slider do painel)
  next|prev        proxima/anterior faixa da playlist do mpv
load <url> <modo> [titulo]
                    troca/insere a faixa: modo replace (default) ou
                    append (tocar a seguir, mpv --idle fica vivo);
                    titulo opcional e guardado no registry (queue_titles.json)
                    para a fila mostrar o nome da musica (nao a URL)
   title <texto>    sobrescreve o media-title via force-media-title
                    (opcao setavel no IPC; media-title e read-only) e guarda
                    o titulo no registry
   loop <off|track|playlist>
                    modo de repeticao (loop-file / loop-playlist do mpv)
   shuffle <on|off> ativa/desativa o shuffle da playlist (propriedade do mpv)
   queue            imprime TSV "idx<TAB>display" da playlist do mpv
                    (display tem ascii '>' marcando a faixa atual; o nome
                    vem do title do entry, do registry, dos caches do bridge
                    meta.json/playlists.json ou do basename do URL)
play <idx>       pula para a faixa idx da playlist (set playlist-pos)
   remove <idx>     remove a faixa idx da playlist (playlist-remove)
   move <idx>       move a faixa idx para a posicao logo apos a atual
                    (playlist-move; "tocar a seguir")
   clear            esvazia a lista de espera do mpv
   playlist         imprime JSON {count, pos} da playlist do mpv
  ping             exit 0 se o mpv estiver tocando/ok, 1 se morto ou ocioso
                   (daemon --idle fica vivo sem faixa; ping so responde "ok"
                   quando ha um arquivo carregado)
"""
import json
import os
import re
import socket
import sys

SOCKET = os.environ.get("MPV_SOCKET", "/tmp/mpv-ytm.sock")
TIMEOUT = 2.0

CACHE_DIR = os.path.expanduser(
    os.environ.get("YTM_CACHE_DIR", "~/.cache/rofi-ytm"))
TITLES_FILE = os.environ.get(
    "YTM_TITLES_FILE", os.path.join(CACHE_DIR, "queue_titles.json"))
META_CACHE_FILE = os.path.join(CACHE_DIR, "meta.json")
PL_CACHE_FILE = os.path.join(CACHE_DIR, "playlists.json")

_VID_RE = re.compile(r"[?&]v=([0-9A-Za-z_-]{11})")


class MpvError(Exception):
    pass


def request(reqs):
    """Envia N requisicoes JSON e aguarda as respostas com request_id."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(TIMEOUT)
    try:
        s.connect(SOCKET)
    except OSError as e:
        raise MpvError(f"mpv not reachable ({e})") from e
    payload = "".join(json.dumps(r) + "\n" for r in reqs)
    s.sendall(payload.encode())
    want = {r.get("request_id") for r in reqs}
    out = {}
    buf = b""
    while want:
        if b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            msg = json.loads(line.decode())
            rid = msg.get("request_id")
            if rid in want:
                out[rid] = msg
                want.discard(rid)
            continue
        chunk = s.recv(65536)
        if not chunk:
            raise MpvError("mpv closed connection")
        buf += chunk
    return out


def result(resp, rid):
    msg = resp.get(rid) or {}
    if msg.get("error") not in (None, "success"):
        raise MpvError(f"mpv error: {msg['error']}")
    return msg.get("data")


def get_state():
    props = ["media-title", "time-pos", "duration", "volume", "pause",
             "filename", "playlist-count", "playlist-pos"]
    reqs = [{"command": ["get_property", p], "request_id": i}
            for i, p in enumerate(props, 1)]
    resp = request(reqs)
    state = {"alive": True}

    def prop(rid, default, cast=str):
        try:
            v = result(resp, rid)
        except MpvError:
            return default
        return default if v is None else cast(v)

    state["title"] = prop(1, "", str)
    state["pos"] = float(prop(2, 0.0, float))
    state["dur"] = float(prop(3, 0.0, float))
    state["vol"] = int(prop(4, 0, int))
    state["paused"] = bool(prop(5, False, bool))
    state["filename"] = prop(6, "", str)
    state["pl_count"] = int(prop(7, 0, int))
    state["pl_pos"] = int(prop(8, -1, int))
    return state


def vid_of(text):
    """Extrai o id do video (11 chars) de uma URL/filename do mpv."""
    if not text:
        return ""
    m = _VID_RE.search(text)
    return m.group(1) if m else ""


def _read_file_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _load_titles():
    return _read_file_cache(TITLES_FILE)


def _save_titles(titles):
    """Grava o registry de titulos atomicamente (tmp + os.replace)."""
    try:
        os.makedirs(os.path.dirname(TITLES_FILE), exist_ok=True)
        tmp = TITLES_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(titles, f)
        os.replace(tmp, TITLES_FILE)
    except OSError:
        pass


def record_title(vid, title):
    titles = _load_titles()
    if titles.get(vid) == title:
        return
    titles[vid] = title
    _save_titles(titles)


def seed_from_playlist_cache(lid):
    """Preenche o registry com os titulos da playlist (cache do bridge
    playlists.json, flat-playlist) para a fila mostrar os nomes na hora."""
    pl = _read_file_cache(PL_CACHE_FILE)
    cached = pl.get(lid) or {}
    entries = cached.get("entries") or []
    if not entries:
        return
    titles = _load_titles()
    changed = False
    for e in entries:
        vid = e.get("_vid") or vid_of(e.get("url") or e.get("webpage_url") or "")
        t = e.get("track") or e.get("title") or ""
        if vid and t and vid not in titles:
            titles[vid] = t
            changed = True
    if changed:
        _save_titles(titles)


def _current_vid():
    """Vid da faixa atual pela playlist do mpv (mais confiavel que a
    propriedade filename, que pode ser o URL resolvido pelo yt-dlp)."""
    try:
        resp = request([{"command": ["get_property", "playlist"], "request_id": 1}])
        for e in result(resp, 1) or []:
            if e.get("current"):
                return vid_of(e.get("filename") or "")
    except MpvError:
        pass
    return ""


def _flatten_pl_titles(pl):
    out = {}
    for _lid, cached in pl.items():
        if not isinstance(cached, dict):
            continue
        for e in cached.get("entries") or []:
            vid = e.get("_vid") or vid_of(e.get("url") or e.get("webpage_url") or "")
            t = e.get("track") or e.get("title") or ""
            if vid and t:
                out.setdefault(vid, t)
    return out


def main():
    if not sys.argv[1:]:
        print("usage: mpvctl.py get|toggle|stop|vol N|seek S|next|prev|"
              "load URL [replace|append] [TITLE]|title T|loop off|track|playlist|"
              "shuffle on|off|queue|play IDX|remove IDX|move IDX|clear|"
              "playlist|ping", file=sys.stderr)
        return 2
    op = sys.argv[1]
    try:
        if op == "get":
            try:
                print(json.dumps(get_state()))
            except MpvError:
                print(json.dumps({"alive": False, "title": "", "pos": 0.0,
                                  "dur": 0.0, "vol": 0, "paused": False}))
        elif op == "toggle":
            request([{"command": ["cycle", "pause"], "request_id": 1}])
        elif op == "stop":
            try:
                request([{"command": ["quit"], "request_id": 1}])
            except MpvError:
                pass
            if os.path.exists(SOCKET):
                try:
                    os.unlink(SOCKET)
                except OSError:
                    pass
        elif op == "vol":
            delta = sys.argv[2] if len(sys.argv) > 2 else ""
            if not delta:
                return 2
            if delta[0] in "+-":
                request([{"command": ["add", "volume", int(delta)], "request_id": 1}])
            else:
                request([{"command": ["set_property", "volume", int(delta)],
                          "request_id": 1}])
        elif op == "seek":
            secs = (sys.argv[2] if len(sys.argv) > 2 else "") or sys.argv[-1]
            if not secs:
                return 2
            request([{"command": ["seek", float(secs), "absolute"], "request_id": 1}])
        elif op in ("next", "prev"):
            request([{"command": [f"playlist-{op}"], "request_id": 1}])
        elif op == "load":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            if not url:
                return 2
            mode = (sys.argv[3] if len(sys.argv) > 3 else "replace").lower()
            title = sys.argv[4] if len(sys.argv) > 4 else ""
            # Forca media-title uma vez por faixa para nao vazar o titulo
            # anterior para a proxima (force-media-title e setavel no IPC;
            # media-title e read-only e o loadfile nao aceita opcoes).
            prep = {"command": ["set_property", "force-media-title", ""],
                    "request_id": 0}
            if url and "list=" in url:
                lid = url.split("list=")[1].split("&")[0]
                if title:
                    record_title(f"pl:{lid}", title)
                seed_from_playlist_cache(lid)
            else:
                vid = vid_of(url)
                if title and vid:
                    record_title(vid, title)
            if mode in ("append", "next"):
                request([prep,
                         {"command": ["loadfile", url, "append-play"],
                          "request_id": 1}])
            else:
                request([prep,
                         {"command": ["loadfile", url, "replace"],
                          "request_id": 1}])
        elif op == "title":
            title = sys.argv[2] if len(sys.argv) > 2 else ""
            if not title:
                return 2
            vid = _current_vid()
            if vid:
                record_title(vid, title)
            request([{"command": ["set_property", "force-media-title", title],
                      "request_id": 1}])
        elif op == "loop":
            state = (sys.argv[2] if len(sys.argv) > 2 else "off").lower()
            if state in ("off", "none", "no"):
                request([{"command": ["set_property", "loop-file", "no"],
                          "request_id": 1},
                         {"command": ["set_property", "loop-playlist", "no"],
                          "request_id": 2}])
            elif state in ("track", "one", "faixa"):
                request([{"command": ["set_property", "loop-file", "inf"],
                          "request_id": 1},
                         {"command": ["set_property", "loop-playlist", "no"],
                          "request_id": 2}])
            elif state in ("playlist", "all"):
                request([{"command": ["set_property", "loop-playlist", "inf"],
                          "request_id": 1}])
            else:
                return 2
        elif op == "shuffle":
            state = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
            if state not in ("on", "yes", "off", "no"):
                return 2
            val = "yes" if state in ("on", "yes") else "no"
            request([{"command": ["set_property", "shuffle", val],
                      "request_id": 1}])
        elif op == "queue":
            resp = request([{"command": ["get_property", "playlist"],
                             "request_id": 1}])
            entries = result(resp, 1) or []
            titles = _load_titles()
            meta = _read_file_cache(META_CACHE_FILE)
            plmap = _flatten_pl_titles(_read_file_cache(PL_CACHE_FILE))
            for i, e in enumerate(entries):
                title = e.get("title") or ""
                fname = e.get("filename") or ""
                vid = vid_of(fname)
                if not title and vid:
                    title = (titles.get(vid)
                             or (meta.get(vid) or {}).get("title")
                             or plmap.get(vid) or "")
                if not title and not vid:
                    m = re.search(r"[?&]list=([0-9A-Za-z_-]+)", fname)
                    if m:
                        title = titles.get("pl:" + m.group(1), "")
                if not title:
                    title = os.path.basename(fname) or "(sem titulo)"
                mark = ">" if e.get("current") else " "
                print(f"{i}\t{mark} {title}")
        elif op == "play":
            idx = sys.argv[2] if len(sys.argv) > 2 else ""
            if not idx.isdigit():
                return 2
            request([{"command": ["set_property", "playlist-pos", int(idx)],
                      "request_id": 1}])
        elif op == "remove":
            idx = sys.argv[2] if len(sys.argv) > 2 else ""
            if not idx.isdigit():
                return 2
            request([{"command": ["playlist-remove", int(idx)],
                      "request_id": 1}])
        elif op == "move":
            # Move a faixa idx para logo apos a atual ("tocar a seguir").
            # Em mpv 0.41 o playlist-move usa indices numericos simples
            # (a variante 'index=N' da 'invalid parameter'). Colocar o item
            # no alvo cur+1 faz ele terminar exatamente nessa posicao,
            # tanto vindo de antes quanto de depois da atual.
            idx = sys.argv[2] if len(sys.argv) > 2 else ""
            if not idx.isdigit():
                return 2
            idx = int(idx)
            try:
                resp = request([{"command": ["get_property", "playlist-pos"],
                                 "request_id": 1}])
                cur = int(result(resp, 1) or -1)
            except MpvError:
                return 1
            if idx in (cur, cur + 1):
                return 0  # ja e a atual ou ja e a proxima
            # cur < 0 = daemon idle no fim da fila: move para o inicio.
            request([{"command": ["playlist-move", idx,
                                  (cur + 1) if cur >= 0 else 0],
                      "request_id": 1}])
        elif op == "clear":
            request([{"command": ["playlist-clear"], "request_id": 1}])
        elif op == "playlist":
            reqs = [{"command": ["get_property", "playlist-count"], "request_id": 1},
                    {"command": ["get_property", "playlist-pos"], "request_id": 2}]
            try:
                resp = request(reqs)
                print(json.dumps({"count": int(result(resp, 1) or 0),
                                  "pos": int(result(resp, 2) or -1)}))
            except MpvError:
                print(json.dumps({"count": 0, "pos": -1}))
        elif op == "ping":
            resp = request([{"command": ["get_property", "filename"],
                             "request_id": 1}])
            val = result(resp, 1)
            if val in (None, "", "null", "none"):
                return 1  # daemon --idle vivo, mas sem faixa carregada
        else:
            print(f"unknown command: {op}", file=sys.stderr)
            return 2
    except MpvError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())