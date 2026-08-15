#!/usr/bin/env python3
"""mpvctl - controle do mpv (rofi-ytm) via JSON IPC. Somente stdlib.

Comandos:
  get              imprime JSON com title/time-pos/duration/volume/pause/
                   filename/playlist-count/playlist-pos/alive
  toggle           alterna play/pause
  stop             encerra o mpv (e remove o socket)
  vol <+N|-N|N>    ajusta o volume (0-130)
  seek <segundos>  pula para a posicao (usado pelo slider do painel)
  next|prev        proxima/anterior faixa da playlist do mpv
  playlist         imprime JSON {count, pos} da playlist do mpv
  ping             exit 0 se o mpv estiver vivo, 1 caso contrario
"""
import json
import os
import socket
import sys

SOCKET = os.environ.get("MPV_SOCKET", "/tmp/mpv-ytm.sock")
TIMEOUT = 2.0


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


def main():
    if not sys.argv[1:]:
        print("usage: mpvctl.py get|toggle|stop|vol N|seek S|next|prev|playlist|ping", file=sys.stderr)
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
            request([{"command": ["get_property", "pause"], "request_id": 1}])
        else:
            print(f"unknown command: {op}", file=sys.stderr)
            return 2
    except MpvError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())