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
ACCOUNT_PREF_FILE = os.path.join(BASE_DIR, "account_pref")
FIREFOX_PROFILE = os.environ.get(
    "YTM_PROFILE",
    os.path.expanduser("__FIREFOX_PROFILE__"),
)
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


def list_accounts(headers):
    """Enumera as contas logadas no navegador via probe de authuser 0..4.

    O endpoint account/accounts_list só lista a conta da sessão atual
    (não enumera multi-login), então cada authuser é validado com
    get_liked_songs e rotulado com get_account_info (keys accountName e
    channelHandle). isSelected fica sempre False — a API não expõe a conta
    ativa; quem marca isso é o account_pref/YTM_AUTHUSER.

    Retorna [{idx, name, handle, isSelected}] das contas válidas ou []
    se nenhuma responder (caller trata como sessão inválida).
    """
    from ytmusicapi import YTMusic

    out = []
    for au in range(0, 5):
        if not session_valid(headers, au):
            continue
        name, handle = "", ""
        try:
            info = YTMusic(dict(headers, **{"x-goog-authuser": str(au)})).get_account_info()
            name = (info.get("accountName") or "").strip()
            handle = (info.get("channelHandle") or "").strip()
        except Exception:
            pass
        out.append({"idx": au, "name": name, "handle": handle, "isSelected": False})
    return out


def session_valid(headers, au):
    from ytmusicapi import YTMusic

    h = dict(headers)
    h["x-goog-authuser"] = str(au)
    try:
        liked = YTMusic(h).get_liked_songs(limit=1)
    except Exception:
        return False
    return liked.get("tracks") is not None


def detect_authuser(headers, preferred=None, accounts=None):
    """Prioriza a conta preferida (preferred); senão a primeira válida por idx.

    accounts vem de list_accounts() (já validadas); se None, enumera aqui.
    """
    if accounts is None:
        accounts = list_accounts(headers)
    idxs = [a["idx"] for a in accounts]
    order = []
    if preferred in idxs:
        order.append(preferred)
    order += [i for i in idxs if i not in order]
    if not order:
        raise RuntimeError(
            "Nenhuma sessão do YouTube Music válida no Firefox "
            "(authuser 0-4). Faça login em youtube.com e tente novamente."
        )
    return str(order[0])


def read_pref():
    """Preferência de conta: arquivo account_pref ou env YTM_AUTHUSER ('auto' = detecção)."""
    val = os.environ.get("YTM_AUTHUSER", "auto").strip()
    if val == "auto":
        try:
            with open(ACCOUNT_PREF_FILE) as f:
                val = f.read().strip()
        except OSError:
            return None
    return int(val) if val in ("0", "1", "2", "3", "4") else None


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
        "x-origin": "https://music.youtube.com",
        "cookie": cookie,
    }
    pref = read_pref()
    accounts = list_accounts(headers)
    if "--list-accounts" in sys.argv:
        for a in accounts:
            label = f"{a['name']} ({a['handle']})".strip()
            print(f"{a['idx']}\t{label}\t{'active' if a['idx'] == pref else ''}")
        return
    au = detect_authuser(headers, pref, accounts)
    headers["x-goog-authuser"] = au
    tmp = BROWSER_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(headers, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, BROWSER_FILE)
    label = f"authuser {au}"
    for a in accounts:
        if a["idx"] == int(au):
            label = f"{a['name']} ({a['handle']})".strip()
            break
    print(f"headers_auth.json refreshed — conta: {label}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"refresh failed: {e}", file=sys.stderr)
        sys.exit(1)