# 03 — Autenticação (headers do navegador + SAPISIDHASH)

## Por que não OAuth?

A primeira tentativa foi o OAuth "oficial" do Google (`ytmusicapi` + device
flow), com um client recriado como **TV and Limited Input devices** (clientes
do tipo "Desktop app" foram rejeitados com `invalid_client` pelo Google em 2026).

O fluxo de dispositivo chegou a funcionar — `oauth.json` foi gravado —, **mas
todas** as chamadas da API retornavam HTTP 400 "Request contains an invalid
argument". É um bug conhecido do Google (issue `sigma67/ytmusicapi#813`, aberta
até fev/2026), sem correção no lado do cliente. O workaround oficial apontado
pela própria comunidade é a **autenticação por headers do navegador**.

> Decisão: `headers_auth.json` + cookies do Firefox é a única via estável.
> Todo o código OAuth foi removido (client_creds.json, oauth.json, device_flow.py).

## Como a credencial é construída

### 1. Cookies do Firefox (snap)

O Firefox do sistema é um **snap**: o perfil vive em
`~/snap/firefox/common/.mozilla/firefox/<perfil>.default/` (não existe
`~/.mozilla`).

O `browser-cookie3` lê o `cookies.sqlite` com a chave de descriptografia do
`key4.db`:

```python
cj = browser_cookie3.firefox(
    cookie_file=os.path.join(FIREFOX_PROFILE, "cookies.sqlite"),
    key_file=os.path.join(FIREFOX_PROFILE, "key4.db"),
)
```

Filtros aplicados:

- domínios: `youtube.com`, `youtubei.googleapis.com`, `googlevideo.com`;
- descarte de rastreio: nomes iniciando em `ST-`, `itct`, `csn`, `PREF`,
  `wide`, `_ga`, `_gcl_au` e valores com mais de 2000 chars (resultado:
  cookie de ~2500 chars, vs. ~37k sem filtro);
- validação de sessão: exige `SAPISID` **ou** `__Secure-3PAPISID` no cookie.

### 2. `DATASYNC_ID` (por sessão)

É extraído do `ytcfg` da **página logada** do YouTube Music:

```python
html = urlopen(Request("https://music.youtube.com", headers={"Cookie": cookie}))
datasync_id = re.search(r'"DATASYNC_ID":"([^"]+)"', html).group(1).split("||")[0]
```

O valor varia por sessão (anônimo ≈ `V590711a6`; logado = valor numérico longo).

### 3. Algoritmo do SAPISIDHASH

```
t      = int(time.time())                      # unix em SEGUNDOS
digest = sha1(f"{datasync_id} {t} {sapisid} https://www.youtube.com").hexdigest()
token  = f"{t}_{digest}_u"
authorization = "SAPISIDHASH <token> SAPISID1PHASH <token> SAPISID3PHASH <token>"
```

Pontos críticos (validados empiricamente):

- timestamp em **segundos** (ms/hmac nunca batem);
- `ORIGIN` é `https://www.youtube.com`, **não** `music.youtube.com`;
- o `SAPISID` usado vem do cookie (mesmo valor de `__Secure-3PAPISID`);
- hoje o Google exige os **3 tokens** (SAPISIDHASH, SAPISID1PHASH,
  SAPISID3PHASH) idênticos;
- o hash gerado funciona imediatamente (não é necessário replicar hash antigo —
  o `DATASYNC_ID` muda por sessão).

### 4. Arquivo `headers_auth.json`

JSON com **chaves minúsculas** (a API do Google as quer assim):

```json
{
  "user-agent": "Mozilla/5.0 ... Firefox/128.0",
  "accept": "*/*",
  "authorization": "SAPISIDHASH <token> ...",
  "accept-language": "pt-BR,pt;q=0.9,en;q=0.5",
  "content-type": "application/json",
  "x-goog-authuser": "2",
  "x-origin": "https://music.youtube.com",
  "cookie": "<todos os cookies>"
}
```

- `x-goog-authuser: 2` — conta secundária (index 2) usada no navegador;
- gravado via arquivo temporário → `chmod 600` → `os.replace` (atômico).

## Auto-recuperação (sem passo manual)

O ciclo vive no `ytm.py`:

```text
chamada da API falha (exceção)
        │
        ▼
refresh_auth()  → roda refresh_auth.py (lê Firefox, recalcula SAPISIDHASH,
        │         sobrescreve headers_auth.json)
        ▼
reconstrói o cliente e TENTA DE NOVO (1 vez)
        │
        ▼
  sucesso → segue o fluxo normal
  falha   → fail("auth error: ...") → notificação crítica na UI
```

Quando o cookie expira (dias/semanas), a próxima busca já regenera tudo
sozinha. As únicas causas de falha real são: Firefox **deslogado** do YouTube
ou **sem conexão**.

## Mensagens de erro (pt-BR) — níveis

| Condição | Mensagem (stderr → notificação) |
|---|---|
| Nenhum cookie de youtube.com no perfil | "Nenhum cookie do YouTube encontrado no Firefox. Abra youtube.com logado e tente novamente." |
| Cookie existe, mas sem sessão (sem SAPISID/__Secure-3PAPISID) | "Sessão do YouTube não encontrada no Firefox. Faça login em youtube.com e tente novamente." |
| Página inacessível (rede/HTML sem DATASYNC_ID) | "Falha ao acessar a página do YouTube Music. Verifique a conexão e tente novamente." |
| `headers_auth.json` inexistente | "No auth found. Run refresh_auth.py first" |

## Env vars de sobrescrita

| Variável | Default | Uso |
|---|---|---|
| `YTM_PROFILE` | `~/snap/firefox/common/.mozilla/firefox/2b11ppm1.default` | perfil do Firefox (mudou o perfil? aponte o novo) |
| `YTM_HEADERS` | `<dir>/headers_auth.json` | caminho alternativo do arquivo de headers |
| `YTM_PYTHON` | python do venv | interpretador usado para refresh_auth.py |

## Segurança e ciclo de vida

- `headers_auth.json` contém **cookies reais** → `chmod 600`, nunca versionar,
  nunca colar em chat/issue. Se vazar: revogar a sessão no navegador
  (Google → "Sair de todas as sessões").
- Cookies expiram; o sistema se recupera sozinho enquanto o Firefox estiver
  logado.
- Os headers de **download** (mpv/yt-dlp) são independentes da API:
  o mpv usa `--cookies-from-browser` direto no perfil do Firefox.