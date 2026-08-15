# 04 — Playback (o caso do 403 e o PO Token)

## Sintoma original

"Algumas músicas tocam e outras não": o mpv abria, mas ficava com **0% de CPU,
sem stream no PipeWire**. No log do mpv:

```text
[ffmpeg] https: HTTP error 403 Forbidden
Failed to open https://rr4---sn-...
"No video or audio streams selected"
exit 2 "Errors when loading file"
```

## Investigação

- `yt-dlp` CLI extraía as URLs dos dois vídeos (bom e ruim) — a extração não
  era o problema;
- testando várias URLs seguidas: ~40–75% das URLs **nasciam mortas** (403),
  com comportamento intermitente e não-determinístico;
- as URLs boas e ruins tinham **parâmetros idênticos** (`itag=251`,
  `c=ANDROID_VR`, `txp=...`) — o único diferenciador era a **ausência de `pot=`**;
- UA diferente, cookie no download e espera de 45s (rate-limit) não mudavam nada;
- o aviso do yt-dlp era a pista:

```text
[youtube] web_music client https formats require a GVS PO Token which was not
provided ... --extractor-args "youtube:po_token=web_music.gvs+XXX"
```

## Causa raiz

Em 2026 o YouTube exige **GVS PO Token** ("Proof of Origin") para clientes
web: sem `pot=`, a URL de stream nasce inválida e o CDN do googlevideo rejeita
com **403 intermitente**. Clientes testados:

| Cliente | Resultado |
|---|---|
| `ANDROID_VR` (default) | não exige pot, mas o CDN rejeita probabilisticamente (~50–75%) |
| `web` | "Only images are available" (sem áudio) |
| `web_safari` | inútil (SABR streaming, formatos sem URL) |
| `web_music` | exige PO Token + cookies; **com pot → áudio 100%** |

## Solução (3 camadas)

### 1. yt-dlp atualizado no venv

O `yt-dlp` do apt é congelado pelo Ubuntu (2026.3.17). Instalado no venv:

```bash
~/.local/share/ytm-venv/bin/pip install -U yt-dlp   # 2026.07.04
```

O mpv 0.41 **não possui `--ytdl-exec`** (removido) — ele resolve o yt-dlp pelo
`PATH`. Por isso o `play_url()` prepara o PATH com o venv na frente.

### 2. deno (runtime JavaScript)

O yt-dlp moderno precisa de um runtime JS para resolver os desafios de
assinatura do player:

```bash
curl -fsSL https://deno.land/install.sh | sh -s -- -y   # ~/.deno/bin/deno
```

Sem deno: "No supported JavaScript runtime could be found... extraction without
a JS runtime has been deprecated".

### 3. Provider de PO Token (bgutil)

```bash
~/.local/share/ytm-venv/bin/pip install -U bgutil-ytdlp-pot-provider   # 1.3.1
git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
(cd ~/bgutil-ytdlp-pot-provider/server && npm ci --frozen-lockfile)
```

- O pacote pip instala o plugin em `yt_dlp_plugins/extractor/getpot_bgutil*.py`;
- o modo **script-deno** roda `deno run ... src/generate_once.ts` do clone
  (cache em `~/.cache/bgutil-ytdlp-pot-provider`);
- verificação: `yt-dlp -v` deve mostrar
  `PO Token Providers: bgutil:script-deno-1.3.1 (external)`.

## A combinação exata de flags (funciona 12/12)

```bash
PATH="$HOME/.local/share/ytm-venv/bin:$HOME/.deno/bin:$PATH" \
mpv --no-video --ytdl-format=bestaudio/best \
  --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
  --ytdl-raw-options="remote-components=ejs:github" \
  --ytdl-raw-options="cookies-from-browser=firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
  'https://music.youtube.com/watch?v=<videoId>'
```

| Flag | Função | Sem ela |
|---|---|---|
| `PATH` (venv + deno) | yt-dlp novo + deno acessíveis ao mpv | "No supported JavaScript runtime" / yt-dlp velho |
| `player_client=web_music` | cliente certo para áudio | `web`: só imagens; default: 403 intermitente |
| `remote-components=ejs:github` | baixa o solver JS de assinaturas | "Signature solving failed... only images" |
| `cookies-from-browser=firefox:<perfil>` | sessão logada (playlists privadas, sem age-gate) | formatos `web_music` são pulados (storyboards) |

Com essas opções o yt-dlp injeta `pot=` na URL e o CDN aceita: **100% de
sucesso em 12/12** (6× "Boys Don't Cry" + 6× "Eu Sou Feliz"), sem precisar de
retry.

> A escolha da flag `--ytdl-format=bestaudio/best` mantém o áudio preferido.
> `--no-terminal` silencia; para depurar use `--msg-level=all=status` no lugar.

## Conta free (sem Premium): sem anúncios, 128 kbps

O pipeline **nunca toca anúncios**, mesmo sem Premium — os ads do YouTube
Music são mídia separada, e o yt-dlp expõe **apenas formatos da música**
(no `-F` não aparecem formatos `ad`/`audio_ad`). O que muda em relação à
conta Premium:

| Aspecto | Efeito |
|---|---|
| Qualidade de áudio | cai para 128 kbps (itag 251/opus ≈ 130 kbps; premium era 256 kbps AAC) |
| PO Token (bgutil) | funciona igual (é anti-bot, não premium) |
| Liked / playlists | depende da conta logada (pode vir vazio em conta nova) |

Verificado empiricamente com conta free: `-F` sem formatos de ad,
`pot=` presente na URL e **3/3 downloads de teste OK** (CDN aceitando o
token). Se algum dia aparecer anúncio costurado no stream (único cenário
que quebraria isso), a mitigação seria filtrar formato no `--ytdl-format`.

## Manutenção

| O que | Como | Quando |
|---|---|---|
| yt-dlp | `~/.local/share/ytm-venv/bin/pip install -U yt-dlp` | após ~90 dias ou erro de extração |
| plugin provider | `.../pip install -U bgutil-ytdlp-pot-provider` | nova versão do plugin |
| provider binário | `cd ~/bgutil-ytdlp-pot-provider && git pull && (cd server && npm ci)` | atualizações do `src/generate_once.ts` |
| deno | `deno upgrade` | quando o yt-dlp exigir |

**Não** remover: o clone `~/bgutil-ytdlp-pot-provider` (o plugin resolve o
script por esse caminho — `getpot_bgutil_script.py` usa
`~ /bgutil-ytdlp-pot-provider / server`), o `node_modules` do server, o venv,
o `~/.deno`.