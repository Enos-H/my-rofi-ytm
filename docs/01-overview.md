# 01 — Visão geral

## O que é

`rofi-ytm` é um sistema que permite **pesquisar e tocar músicas da conta do
usuário no YouTube Music usando apenas o rofi** (launcher estilo dmenu) e o
`mpv`, num fluxo 100% teclado, sem abrir navegador nem interface gráfica de
música.

Ele substitui o antigo protótipo `rofi-blocks` (que dependia de um fork do
rofi com o modi `blocks`, indisponível na build do sistema) por uma solução
baseada em `rofi -dmenu` encadeado — compatível com o rofi 1.7.8+wayland1
padrão e com os temas já existentes (KoolDots).

## Stack

| Camada | Tecnologia | Papel |
|---|---|---|
| UI | `rofi -dmenu` (temas `config-rofi-Beats*.rasi`) | Menus e listas |
| Orquestração | Bash (`RofiYtm.sh`) | Fluxo de telas, notificações, mpv |
| API | `ytmusicapi` 1.12.2 (Python 3.14, venv `ytm-venv`) | busca, curtidas, playlists |
| Auth | `browser-cookie3` 0.20.1 + SAPISIDHASH | credenciais a partir do Firefox |
| Playback | `mpv` 0.41.0 + `yt-dlp` 2026.07.04 (venv) | streaming de áudio |
| PO Token | `deno` + `bgutil-ytdlp-pot-provider` 1.3.1 | tornar as URLs de stream válidas |
| Notificação | `notify-send` (swaync + ícone `music.png`) | feedback visual |

## Funcionalidades

1. **Search YouTube Music** — `yt.search(q, filter="songs", limit=20)` no
   catálogo público (não precisa de login, mas usa o autenticado).
2. **Liked Songs** — `yt.get_liked_songs(limit=100)`.
3. **My Playlists** — `yt.get_library_playlists(limit=None)` (todas da biblioteca);
   cada playlist abre um submenu:
   - **Play whole playlist** → mpv recebe `https://music.youtube.com/playlist?list=<id>`;
   - **Pick a song** → `yt.get_playlist(<id>, limit=200)` e escolha de faixa.

Toda seleção dispara o `play_url()`, que derruba a música anterior (sem matar
o `mpvpaper`) e toca a nova em background com notificação "Now Playing".

## Fluxo

```text
SUPER SHIFT Y  (ou RofiBeats > "Play from YouTube Music 🎧")
      │
      ▼
┌─────────────────────────┐
│ 🔎 Search YouTube Music │── query via rodi ─> ytm.py search ─> lista rofi ─> watch?v=<id>
│ ❤️  Liked Songs         │────────────────── ytm.py liked ───> lista rofi ─> watch?v=<id>
│ 📁 My Playlists         │────────────────── ytm.py playlists > lista rofi
└─────────────────────────┘                        │
                                                   ├─ "Play whole playlist" > playlist?list=<id>
                                                   └─ "Pick a song" > ytm.py playlist <id> > rofi > watch?v=<id>
        │
        ▼
   play_url(<url>)
      │
      ├── stop_music()  (mata mpv antigo, preserva mpvpaper)
      ├── notification "Now Playing: <título>"
      └── setsid mpv --no-video ... <url>  (yt-dlp + PO token embutidos)
```

## Mapa de arquivos

### Do sistema (fora deste repo)

| Arquivo | Responsabilidade | Linhas |
|---|---|---|
| `~/.config/hypr/UserScripts/RofiYtm.sh` | UI rofi + playback | ~116 |
| `~/.config/rofi/scripts/ytm/ytm.py` | helper ytmusicapi (4 comandos) | ~131 |
| `~/.config/rofi/scripts/ytm/refresh_auth.py` | regenera auth automaticamente | ~105 |
| `~/.config/rofi/scripts/ytm/headers_auth.json` | credencial ativa (600, secreto) | — |
| `~/.local/share/ytm-venv/` | ambiente Python isolado | — |
| `~/bgutil-ytdlp-pot-provider/` | provider binário de PO Token | — |
| `~/.deno/bin/deno` | runtime JS do yt-dlp | — |

### Temporários (regenerados a cada listagem)

| Arquivo | Conteúdo |
|---|---|
| `/tmp/ytm_songs.tsv` | `número_da_linha \t videoId/playlistId` |
| `/tmp/ytm_songs.lines` | linhas exatas de exibição (título - artista (duração)) |

O par TSV+LINES é a ponte entre a saída do Python e a seleção do rofi: o rofi
exibe `LINES_FILE`, e a escolha é resolvida de volta ao ID via número de linha
(veja [`02-architecture.md`](02-architecture.md)).

## Integrações

- `~/.config/hypr/UserScripts/RofiBeats.sh` — item de menu
  **"Play from YouTube Music 🎧"** que delega para o `RofiYtm.sh`.
- `~/.config/hypr/configs/system_keybinds.lua` — `bind("SUPER SHIFT", "Y", ...)`
  com descrição "youtube music".
- `~/.config/hypr/configs/Keybinds.conf` — `bindd = $mainMod SHIFT, Y, YouTube Music, exec, $UserScripts/RofiYtm.sh`.

> Nota: as integrações formatam features do Hyprland via keybindd e RofiBeats;
> o núcleo (rofi + helpers) é desktop-agnostic.