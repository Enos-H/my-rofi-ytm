# 01 — Visão geral e funcionalidades

## O que é

`rofi-ytm` é um sistema que permite **pesquisar e tocar músicas da conta do
usuário no YouTube Music usando apenas o rofi** (launcher estilo dmenu) e o
`mpv`, num fluxo 100% teclado, sem abrir navegador nem interface gráfica de
música. A reprodução é acompanhada por dois painéis auxiliares: o **Hyprwave**
(painel "Now Playing" com capa, progresso, volume e controles MPRIS) e um
**painel de letras** (karaokê ANSI em uma janela kitty).

Substituiu o antigo protótipo `rofi-blocks` (que dependia de um fork do rofi
com o modi `blocks`, indisponível na build do sistema) por uma solução
baseada em `rofi -dmenu` encadeado — compatível com o rofi 1.7.8+wayland1
padrão e com os temas já existentes (KoolDots/Beats).

## Stack

| Camada | Tecnologia | Papel |
|---|---|---|
| UI | `rofi -dmenu` (temas `config-rofi-Beats*.rasi`) | Menus e listas |
| Orquestração | Bash (`RofiYtm.sh`) | Fluxo de telas, mpv, painéis |
| API | `ytmusicapi` 1.12.2 (venv `ytm-venv`) | busca, curtidas, playlists |
| Auth | `browser-cookie3` 0.20.1 + SAPISIDHASH | credenciais a partir do Firefox |
| Playback | `mpv` 0.41.0 + `yt-dlp` 2026.07.04 (venv) | streaming de áudio |
| PO Token | `deno` + `bgutil-ytdlp-pot-provider` 1.3.1 | URLs de stream válidas (`pot=`) |
| Painel | Hyprwave v1.1 (patched) | "Now Playing": capa, progresso, volume, ondas |
| Letras | `lyrics_player.py` + lrclib.net + kitty | karaokê ANSI sincronizado |
| Notificação | `notify-send` (swaync) | feedback de erros/estado |

## Funcionalidades completas

### Menu principal (7 entradas)

`SUPER SHIFT Y` (ou RofiBeats > "Play from YouTube Music 🎧") abre o menu:

| Entrada | O que faz |
|---|---|
| 🔎 **Search YouTube Music** | busca no catálogo público (`filter="songs"`, 20 resultados); escolheu → toca |
| ❤️ **Liked Songs** | suas músicas curtidas (até 100) |
| 📁 **My Playlists** | todas as playlists da biblioteca, com submenu |
| 🎧 **Now Playing** | reabre o painel Hyprwave (se o mpv estiver vivo) |
| 🎤 **Letras** | submenu do painel de letras (mostrar/esconder + 3 tamanhos) |
| 👁️ **Mostrar/Esconder Painel** | alterna a visibilidade do Hyprwave (estado manual) |
| 🔄 **Recarregar Cookies** | regenera a autenticação; com 2+ contas abre um seletor |

### Submenu Playlists

- ▶️ **Play whole playlist** — toca a playlist inteira pelo ID
  (`https://music.youtube.com/playlist?list=<id>`) — o yt-dlp expande todas
  as faixas no mpv, e o painel ganha **próxima/anterior**;
- 🎵 **Pick a song** — lista as faixas (até 200) e você escolhe uma.

### Playback

- A música anterior é **sempre encerrada** antes de tocar a próxima
  (preservando o `mpvpaper`, se estiver rodando);
- mpv com `--input-ipc-server=/tmp/mpv-ytm.sock` (controle externo via
  `mpvctl.py`) e `--force-media-title` com o **nome real** da música
  (sufixo de duração ` (m:ss)` removido);
- Cliente `web_music` + PO Token (bgutil/deno) → **sem anúncios**, sem 403
  (detalhes em `04-playback.md`);
- Conta **free** funciona: 128 kbps (itag 251/opus), sem ads;
- Qualquer cliente MPRIS controla o mpv (`playerctl -p ytm ...`).

### Painel "Now Playing" (Hyprwave)

- **Nome real** da música e **thumbnail** do YouTube como arte (via bridge
  MPRIS `org.mpris.MediaPlayer2.ytm` — o mpv nativo não permite customizar);
- Progresso ao vivo, slider de volume, play/pause e **próxima/anterior**
  (habilitados quando a faixa atual está numa playlist);
- **Visualizer de ondas** (espectro real via PulseAudio), com fix de
  jitter/congelamento (patches);
- Esconder/mostrar manualmente: menu `👁️` ou `SUPER CTRL Y` (estado gravado
  em `/tmp/ytm_panel_hidden` — tocar música **respeita** o estado manual);
- Ao parar, o painel fica aberto no visualizer idle (não é fechado).

### Painel de letras (karaokê ANSI)

- Janela `kitty` flutuante (`--class ytm-lyrics`), abre junto com a música e
  fecha no stop; `SUPER CTRL L` ou menu `🎤` alternam manualmente;
- Letras do **lrclib.net**: LRC sincronizado quando existe, fallback letra
  completa distribuída pela duração, aviso para instrumental, "Letra não
  encontrada" quando não há registro;
- **Layout adaptável** ao tamanho do terminal (re-renderiza em resize),
  quebra só por **palavra inteira** e espaçamento inteligente (linhas do
  mesmo verso consecutivas, exatamente 1 vazia entre versos);
- 3 tamanhos: Compacta 420×300 / Média 600×400 / Grande 800×600;
- Janela **fixa em todos os workspaces** (`pin` — acompanha o painel) e
  **nunca rouba o foco** (`no_initial_focus` + `no_focus`, display-only).

### Autenticação e multi-conta

- Credencial (`headers_auth.json`) gerada a partir dos **cookies do Firefox**
  + SAPISIDHASH; regenerada automaticamente quando expira;
- Com **2+ contas logadas**, `🔄 Recarregar Cookies` abre um seletor
  (`•` = preferida, gravada em `account_pref`; o header `x-goog-authuser`
  define a conta usada pela API);
- Download (mpv/yt-dlp) usa `--cookies-from-browser` direto no perfil do
  Firefox — independente dos headers da API.

## Fluxo

```text
SUPER SHIFT Y  (ou RofiBeats > "Play from YouTube Music 🎧")
      │
      ▼
┌─────────────────────────┐
│ 🔎 Search YouTube Music │── query via rofi ─▶ ytm.py search ─▶ lista rofi ─▶ watch?v=<id>
│ ❤️  Liked Songs         │──────────────────── ytm.py liked ──▶ lista rofi ─▶ watch?v=<id>
│ 📁 My Playlists         │──────────────────── ytm.py playlists ▶ lista rofi
│ 🎧 Now Playing          │──────────────────── reabre o painel (se mpv vivo)
│ 🎤 Letras               │──────────────────── submenu letras
│ 👁️  Mostrar/Esconder   │──────────────────── toggle painel (flag manual)
│ 🔄 Recarregar Cookies   │──────────────────── refresh auth (+ seletor conta)
└─────────────────────────┘                        │
                                                   ├─ "Play whole playlist" ▶ playlist?list=<id>
                                                   └─ "Pick a song" ▶ ytm.py playlist <id> ▶ rofi ▶ watch?v=<id>
        │
        ▼
   play_url(<url>, <título real>)
      │
      ├── stop_music()  (mata mpv antigo, preserva mpvpaper; fecha letras)
      ├── setsid mpv --no-video ... (socket IPC + force-media-title + PO token)
      ├── open_panel()  (spawna hyprwave se ausente + bridge MPRIS + mostra painel)
      └── lyrics-panel-toggle open  (janela de letras junto)
```

## Mapa de arquivos (deploy)

### Scripts do sistema (deployados pelo `install.sh` a partir de `src/`)

| Arquivo | Responsabilidade |
|---|---|
| `~/.config/hypr/UserScripts/RofiYtm.sh` | UI rofi + playback + orquestração dos painéis |
| `~/.config/rofi/scripts/ytm/ytm.py` | helper ytmusicapi (search/liked/playlists/playlist) |
| `~/.config/rofi/scripts/ytm/refresh_auth.py` | regenera `headers_auth.json` (cookies Firefox + SAPISIDHASH + seletor de conta) |
| `~/.config/rofi/scripts/ytm/mpvctl.py` | cliente do socket JSON do mpv (`get/toggle/stop/vol/seek/next/prev/playlist/ping`) |
| `~/.config/rofi/scripts/ytm/mpris_bridge.py` | player MPRIS `org.mpris.MediaPlayer2.ytm` (título real + artUrl + CanGoNext/Prev) |
| `~/.config/rofi/scripts/ytm/lyrics_player.py` | karaokê ANSI (lê a bridge via D-Bus + lrclib.net) |
| `~/.local/bin/hyprwave-panel-toggle` | mostra/esconde o painel (menu + `SUPER CTRL Y`) |
| `~/.local/bin/lyrics-panel-toggle` | abre/fecha/redimensiona a janela de letras (menu + `SUPER CTRL L`) |
| `~/.config/rofi/scripts/ytm/headers_auth.json` | credencial ativa (chmod 600, secreto) |
| `~/.config/rofi/scripts/ytm/account_pref` | conta preferida (multi-login) |

### Infraestrutura

| Caminho | Papel |
|---|---|
| `~/.local/share/ytm-venv/` | venv Python (ytmusicapi, browser-cookie3, yt-dlp, bgutil, dbus-next) |
| `~/bgutil-ytdlp-pot-provider/` | provider binário de PO Token (clone + `server/node_modules`) |
| `~/.deno/bin/deno` | runtime JS do yt-dlp (assinaturas + PO token) |
| `~/.local/bin/hyprwave` | painel "Now Playing" (build patched) |
| `~/.config/hyprwave/config.conf` | config do hyprwave (`preference = ytm,mpv,spotify,vlc`) |

### Temporários (regenerados a cada listagem)

| Arquivo | Conteúdo |
|---|---|
| `/tmp/ytm_songs.tsv` | `número_da_linha \t videoId/playlistId` |
| `/tmp/ytm_songs.lines` | linhas exatas de exibição (título - artista (duração)) |
| `/tmp/mpv-ytm.sock` | socket IPC do mpv |
| `/tmp/ytm_bridge.pid`, `/tmp/ytm_lyrics.pid` | pidfiles da bridge e do player de letras |
| `/tmp/ytm_panel_hidden` | flag de estado manual (painel escondido) |

O par TSV+LINES é a ponte entre a saída do Python e a seleção do rofi: o rofi
exibe `LINES_FILE`, e a escolha é resolvida de volta ao ID via número de linha.

## Integrações

- `~/.config/hypr/UserScripts/RofiBeats.sh` — item de menu
  **"Play from YouTube Music 🎧"** que delega para o `RofiYtm.sh`;
- `~/.config/hypr/configs/Keybinds.conf` — os 3 binds (detalhe em `02-architecture.md`):
  `SUPER SHIFT Y` (launcher), `SUPER CTRL Y` (painel), `SUPER CTRL L` (letras);
- `~/.config/hypr/configs/WindowRules.conf` — windowrules da janela de letras
  (`ytm-lyrics`: float, size, move, pin, no_focus);
- `system_keybinds.lua` — bind equivalente do launcher (`SUPER SHIFT Y`).

> O núcleo (rofi + helpers + mpv) é desktop-agnostic; as integrações de
> keybind/painel são específicas do Hyprland deste ambiente.
