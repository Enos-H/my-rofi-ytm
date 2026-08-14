#!/usr/bin/env python3
"""rofi-ytm helper - YouTube Music via ytmusicapi.

Subcommands:
  search <query>   search songs in the YTM catalog
  liked            list liked songs
  playlists        list library playlists
  playlist <id>    list tracks of a playlist

Each command prints one display line per result and writes
/tmp/ytm_songs.tsv mapping line number -> videoId/playlistId,
plus /tmp/ytm_songs.lines with the exact display lines.
"""
import json
import os
import subprocess
import sys

from ytmusicapi import YTMusic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BROWSER_FILE = os.path.join(BASE_DIR, "headers_auth.json")
REFRESH_SCRIPT = os.path.join(BASE_DIR, "refresh_auth.py")
TSV_FILE = "/tmp/ytm_songs.tsv"
LINES_FILE = "/tmp/ytm_songs.lines"

RESULT_COUNT = 20


def fail(msg):
    print(msg, file=sys.stderr)
    print(f'{{"message": "{msg}", "prompt": "error"}}')
    sys.exit(1)


def get_client():
    browser_path = os.environ.get("YTM_HEADERS", BROWSER_FILE)
    if not os.path.exists(browser_path):
        fail("No auth found. Run refresh_auth.py first")
    return YTMusic(browser_path)


def refresh_auth():
    py = os.environ.get("YTM_PYTHON", sys.executable)
    p = subprocess.run([py, REFRESH_SCRIPT], capture_output=True, timeout=60)
    if p.returncode != 0:
        err = (p.stderr or b"").decode("utf-8", "ignore").strip() or "refresh failed"
        fail(err)


def run(yt, cmd, args):
    if cmd == "search":
        query = " ".join(args)
        if not query:
            fail("empty search query")
        songs = yt.search(query, filter="songs", limit=RESULT_COUNT)
        emit(songs, [s.get("videoId", "") for s in songs])

    elif cmd == "liked":
        liked = yt.get_liked_songs(limit=100)
        tracks = [t for t in liked.get("tracks", []) if t.get("videoId")]
        emit(tracks, [t["videoId"] for t in tracks])

    elif cmd == "playlists":
        playlists = yt.get_library_playlists(limit=None)
        lines = [f"{p['title']} ({p.get('count', 0)} tracks)" for p in playlists]
        with open(TSV_FILE, "w") as tsv:
            for i, p in enumerate(playlists, start=1):
                tsv.write(f"{i}\t{p['playlistId']}\n")
        with open(LINES_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
        print("\n".join(lines))

    elif cmd == "playlist":
        pid = args[0] if args else ""
        if not pid:
            fail("missing playlist id")
        pl = yt.get_playlist(pid, limit=200)
        tracks = [t for t in pl.get("tracks", []) if t.get("videoId")]
        emit(tracks, [t["videoId"] for t in tracks])

    else:
        fail(f"unknown command: {cmd}")


def main():
    args = sys.argv[1:]
    if not args:
        fail("usage: ytm.py search <q> | liked | playlists | playlist <id>")
    cmd = args[0]
    try:
        run(get_client(), cmd, args[1:])
    except Exception as e:
        refresh_auth()
        try:
            run(get_client(), cmd, args[1:])
        except Exception as e2:
            fail(f"auth error: {e2}")


def duration_str(track):
    if track.get("duration"):
        return f" ({track['duration']})"
    secs = track.get("duration_seconds")
    if secs:
        return f" ({secs // 60}:{secs % 60:02d})"
    return ""


def artist_str(track):
    artists = track.get("artists") or []
    return ", ".join(a["name"] for a in artists if a.get("name"))


def emit(tracks, ids):
    lines = []
    with open(TSV_FILE, "w") as tsv:
        for i, track in enumerate(tracks, start=1):
            title = track.get("title") or "Unknown"
            display = title + duration_str(track)
            if artist_str(track):
                display = f"{title} - {artist_str(track)}{duration_str(track)}"
            lines.append(display)
            tsv.write(f"{i}\t{ids[i - 1]}\n")
    with open(LINES_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()