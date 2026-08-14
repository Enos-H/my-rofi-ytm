# 06 — História do projeto (jornada e decisões)

Este documento registra o raciocínio por trás de cada escolha. Serve para
entender **por que** o sistema é como é — e para não repetir becos sem saída.

---

## Fase 1 — Análise do contexto (o que não servia)

Os dotfiles usam Hyprland (KoolDots/LinuxBeginnings) com **rofi-beats** já
configurado. O protótipo original `rofi-ytm` (rofi-blocks) dependia de um fork
do rofi com o modi `blocks` — a build instalada (`/usr/local/bin/rofi`)
é a 1.7.8+wayland1 **sem** esse modi, e trocar o rofi quebraria os temas.
Alternativas web pesquisadas (QuickMedia, youtube-viewer, ytdl-mpv) **não
acessam a conta** do YouTube Music — todas foram descartadas.

**Decisão:** `rofi -dmenu` encadeado + `ytmusicapi` + `mpv`.

## Fase 2 — OAuth: tentado, abandonado por bug do Google

- Client "Desktop app" no Google Cloud → `invalid_client` no device flow
  (Google restringiu o tipo; só "TV and Limited Input devices" funciona).
- Client TV criado → device flow funcionou, `oauth.json` gravado.
- **Porém:** toda chamada da API → HTTP 400 "Request contains an invalid
  argument" — bug conhecido (issue `sigma67/ytmusicapi#813`, ainda aberta em
  fev/2026). Workaround oficial: browser headers.

**Decisão:** abandonar OAuth; limpar client_creds.json/oauth.json/device_flow.py.
O `get_client()` ficou 100% browser headers.

## Fase 3 — Headers manuais e as armadilhas do paste

Copiamos os headers do navegador para `headers_auth.json` e descobrimos
armadilhas do copy-paste:

1. A primeira linha do painel de rede (`POST /youtubei/... HTTP/3`) vira uma
   chave lixo no JSON → erro HTML 400 do frontend. **Remover.**
2. O header `content-encoding: gzip` é de **resposta**, não de requisição:
   deixa o servidor esperando body gzip. **Remover.**
3. As chaves do JSON são **minúsculas** — `json.load(...)['Cookie']` dá len 0.

**Decisão:** manter chaves minúsculas, sem `POST ... HTTP/3`, sem
content-encoding.

## Fase 4 — Automação da auth: cookies do Firefox + SAPISIDHASH

O usuário não queria extrair headers na mão a cada expiração. Surgiu o
`refresh_auth.py`:

- `browser-cookie3` lê o perfil **snap** do Firefox
  (`~/snap/firefox/common/.mozilla/firefox/*.default` — `cookies.sqlite` +
  `key4.db`), sem senha-mestra, com o Firefox aberto;
- descarte de cookies de rastreio (cookie final de ~2.5k chars);
- **descoberta do DATASYNC_ID**: chave do `ytcfg` da página logada, parte
  antes de `||`;
- **algoritmo do SAPISIDHASH** (validado empiricamente, depois de tentativas
  frustradas com ms, hmac e origin music.youtube.com):

```
sha1(f"{datasync_id} {int(time.time())} {sapisid} https://www.youtube.com")
```

- auto-recuperação no `ytm.py`: exceção → rodar refresh → **1 retry**;
- mensagens de erro em pt-BR com 3 níveis (sem cookies / deslogado / sem rede).

**Decisão:** primeira auth automática; nunca mais passo manual enquanto o
Firefox estiver logado.

## Fase 5 — A saga do 403 (PO Token)

"Algumas tocam e outras não": mpv vivo com 0% CPU, `[ffmpeg] https: HTTP error
403 Forbidden`. A investigação mostrou:

- yt-dlp CLI extraía URLs de tudo, mas ~40–75% nasciam **mortas**;
- URLs boas e ruins tinham parâmetros idênticos; só faltava **`pot=`**;
- cada cliente testado tinha uma falha (tabela em 04-playback.md);
- pista final do yt-dlp: clientes web exigem **GVS PO Token**.

Componentes instalados na ordem (e por quê):

1. **deno** — yt-dlp 2026 exige runtime JS para assinaturas;
   `curl -fsSL https://deno.land/install.sh` → `~/.deno/bin/deno`;
2. **yt-dlp via pip no venv** — o apt congela em 2026.3.17; pip tem
   2026.07.04 (mpv 0.41 não tem `--ytdl-exec`, usa o PATH);
3. **bgutil-ytdlp-pot-provider** — pip plugin + clone
   `~/bgutil-ytdlp-pot-provider` + `npm ci` no `server/`; modo script-deno
   (`yt-dlp -v` → `PO Token Providers: bgutil:script-deno-1.3.1`).

O `play_url()` final combina `web_music` + `ejs:github` + cookies do perfil
snap → URLs com `pot=` → **12/12 playbacks** (6× Boys Don't Cry + 6× Eu Sou
Feliz). Retry nunca foi necessário.

## Fase 6 — Limpezas

| Removido | Motivo |
|---|---|
| `client_creds.json`, `oauth.json`, `device_flow.py` | código morto do OAuth abandonado |
| `auth.py` (modo manual) | ninguém referenciava; o refresh_auth.py faz o papel |
| `__pycache__/` do diretório ytm | bytecode lixo |
| symlink `𝜋thon` no venv/bin | arquivo acidental não usado |
| pasta `rofi-ytm` original (com .git) | protótipo rofi-blocks substituído — recriada apenas com docs |

## Lições gerais (para não repetir)

1. **Nunca** `pkill -f` com padrão presente na própria linha de comando do
   shell (mata o shell). Use `pkill -x mpv` / `pgrep -x`.
2. Ao refatorar `ytm.py`, verifique o guard `if __name__ == "__main__": main()`.
3. `mpv --no-terminal` suprime o log inteiro — para depurar use
   `--msg-level=all=status`.
4. `grep -nFx` (literal + linha inteira) para casar a escolha do rofi com o
   arquivo de linhas (acentos/emoji seguros).
5. Plugins pip do yt-dlp só valem para o yt-dlp **daquele Python** (venv).
6. Rotular sempre que um arquivo contém segredos: `headers_auth.json` é
   chmod 600 e nunca vai para git/chat.