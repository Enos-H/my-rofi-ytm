#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BROWSER_FILE = os.path.join(BASE_DIR, "headers_auth.json")
FIREFOX_PROFILE = os.environ.get("YTM_PROFILE", "__FIREFOX_PROFILE__")
ORIGIN = "https://www.youtube.com"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
YTM_DOMAINS = ("youtube.com", "youtubei.googleapis.com", "googlevideo.com")


def get_cookies():
    from browser_cookie3 import firefox

    cj = firefox(
        cookie_file=os.path.join(FIREFOX_PROFILE, "cookies.sqlite"),
        key_file=os.path.join(FIREFOX_PROFILE, "key4.db"),
    )
    cookies = [c for c in cj if any(d in c.domain for d in YTM_DOMAINS)]
    if not cookies:
        raise RuntimeError(
            "Nenhum cookie do YouTube encontrado no Firefox. "
            "Abra youtube.com logado e tente novamente."
        )
    skip_names = {"ST-", "itct", "csn", "PREF", "wide", "_ga", "_gcl_au"}
    wanted = [
        c
        for c in cookies
        if not any(c.name.startswith(s) for s in skip_names) and len(c.value) < 2000
    ]
    drop = len(cookies) - len(wanted)
    if drop:
        print(f"skipped {drop} tracking cookies", file=sys.stderr)
    cookie = "; ".join(f"{c.name}={c.value}" for c in wanted)
    if not re.search(r"(?:__Secure-3PAPISID|SAPISID)=[^;]+", cookie):
        raise RuntimeError(
            "Sessão do YouTube não encontrada no Firefox. "
            "Faça login em youtube.com e tente novamente."
        )
    return cookie


def get_datasync_id(cookie):
    req = urllib.request.Request(
        "https://music.youtube.com",
        headers={"User-Agent": UA, "Cookie": cookie},
    )
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    m = re.search(r'"DATASYNC_ID":"([^"]+)"', html)
    if not m:
        raise RuntimeError(
            "Falha ao acessar a página do YouTube Music. "
            "Verifique a conexão e tente novamente."
        )
    return m.group(1).split("||")[0]


def make_sapisidhash(cookie, datasync_id):
    m = re.search(r"(?:__Secure-3PAPISID|SAPISID)=([^;]+)", cookie)
    if not m:
        raise RuntimeError("SAPISID cookie not found")
    sapisid = m.group(1)
    t = str(int(time.time()))
    digest = hashlib.sha1(f"{datasync_id} {t} {sapisid} {ORIGIN}".encode()).hexdigest()
    token = f"{t}_{digest}_u"
    return f"SAPISIDHASH {token} SAPISID1PHASH {token} SAPISID3PHASH {token}"


def main():
    cookie = get_cookies()
    datasync_id = get_datasync_id(cookie)
    auth = make_sapisidhash(cookie, datasync_id)
    headers = {
        "user-agent": UA,
        "accept": "*/*",
        "authorization": auth,
        "accept-language": "pt-BR,pt;q=0.9,en;q=0.5",
        "content-type": "application/json",
        "x-goog-authuser": "2",
        "x-origin": "https://music.youtube.com",
        "cookie": cookie,
    }
    tmp = BROWSER_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(headers, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, BROWSER_FILE)
    print(f"headers_auth.json refreshed ({len(cookie)} chars cookie)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"refresh failed: {e}", file=sys.stderr)
        sys.exit(1)