# 02 — Arquitetura completa

Este documento detalha cada componente do sistema, seu contrato, como se
comunicam, as dependências (sistema, Python, externas), os repositórios git
envolvidos e o **ambiente real onde roda** (sistema do autor, com versões).

---

## 1. Visão geral em camadas

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                          HYPRELAND (compositor)                          │
│  keybinds: SUPER SHIFT Y · SUPER CTRL Y · SUPER CTRL L                   │
│  windowrules: ytm-lyrics (float/pin/no_focus)                            │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ exec
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  RofiYtm.sh (Bash) — launcher/menu principal (9 entradas)                │
│   · ytm.py/refresh_auth.py  → API YouTube Music (ytmusicapi)             │
│   · pick_from_helper: TSV+LINES → rofi → watch/playlist URL              │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │ toca                           │ spawna
                ▼                                ▼
┌──────────────────────────────┐   ┌─────────────────────────────────────┐
│  mpv (--input-ipc-server)    │   │  mpris_bridge.py (venv, dbus-next)   │
│  yt-dlp+deno+bgutil (pot=)   │   │  org.mpris.MediaPlayer2.ytm          │
│  MPRIS nativo (fallback)     │   │  título real · artUrl · next/prev    │
└──────────────┬───────────────┘   └──────────────┬──────────────────────┘
               │ IPC JSON (socket /tmp/mpv-ytm.sock)   │ D-Bus session bus
               ▼                                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  mpvctl.py — cliente do socket (get/toggle/vol/seek/next/prev/load/   │
│              title/loop/shuffle/queue/play/clear/playlist/ping)      │
└──────────────────────────────────────────────────────────────────────────┘
               │                                              │
               ▼ D-Bus MPRIS                                   ▼ D-Bus MPRIS
┌──────────────────────────────┐                  ┌───────────────────────┐
│  Hyprwave (painel Now Playing)│                  │  lyrics_player.py     │
│  · capa (artUrl https)        │                  │  lrclib.net (LRC)     │
│  · progresso/volume/controles │                  │  karaokê ANSI         │
│  · visualizer (PulseAudio)    │                  │  kitty (ytm-lyrics)   │
└──────────────────────────────┘                  └───────────────────────┘
```

Camadas e o que flui entre elas:

| Fluxo | Canal | Direção |
|---|---|---|
| Launcher → API YTM | HTTP (ytmusicapi, headers auth) | busca/curtidas/playlists |
| Launcher → mpv | exec (setsid, 1x — daemon) + IPC `loadfile` | toca/enfileira URL |
| Launcher/bridge ↔ mpv | **IPC JSON** (unix socket `/tmp/mpv-ytm.sock`) | get/load/title/toggle/vol/seek/next/prev/queue |
| Bridge → consumidores | **D-Bus** (`org.mpris.MediaPlayer2.ytm`) | metadata + métodos MPRIS |
| Bridge → mpv | socket persistente + `observe_property`/eventos | estado sem polling por subprocesso |
| Bridge → consumidores | **D-Bus** (`org.mpris.MediaPlayer2.ytm`) | metadata + métodos MPRIS |
| Bridge → yt-dlp | subprocess (só p/ título/artista fallback) | enriquecer metadata |
| Hyprwave ↔ PulseAudio | `@DEFAULT_MONITOR@` | amostras p/ visualizer |
| Letras → lrclib.net | HTTP (GET/Search) | letras LRC |
| Painel ↔ launcher | pidfiles + signals (SIGUSR1/2, SIGRTMIN) | toggle visibilidade/expand/play |
| Estado manual | arquivos `/tmp/ytm_*.{pid,hidden}` | flags entre processos |

---

## 2. Componentes em detalhe

### 2.1 `RofiYtm.sh` — launcher (Bash)

**Deploy:** `~/.config/hypr/UserScripts/RofiYtm.sh` (ou `~/.local/bin`).

**Variáveis globais:**

| Variável | Valor | Uso |
|---|---|---|
| `iDIR` | `$CONFIG_DIR/swaync/icons` | ícone das notificações (`music.png`) |
| `rofi_theme` / `rofi_theme_menu` | `config-rofi-Beats*.rasi` | temas |
| `PYTHON` | `$VENV_DIR/bin/python` | Python do venv |
| `HELPER` / `REFRESH_AUTH` / `MPVCTL` / `BRIDGE` | `$CONFIG_DIR/rofi/scripts/ytm/*` | helpers |
| `MPV_SOCKET` | `/tmp/mpv-ytm.sock` | IPC do mpv |
| `BRIDGE_PID_FILE` / `PANEL_HIDDEN_FLAG` | `/tmp/ytm_bridge.pid` / `/tmp/ytm_panel_hidden` | flags |
| `TSV_FILE` / `LINES_FILE` | `/tmp/ytm_songs.{tsv,lines}` | ponte rofi |
| `export PATH="$HOME/.local/bin:$PATH"` | — | hyprwave/hyprwave-toggle acessíveis (o PATH do Hyprland não tem `~/.local/bin`) |

**Funções principais:**

- `notification()` — `notify-send -u normal -i "$iDIR/music.png"` (erros e
  feedbacks; a notificação "Now Playing" foi removida — o hyprwave notifica);
- `spawn_mpv_idle()` — sobe o daemon mpv `--idle` (flags yt-dlp + `--vo=null`
  + socket + `--log-file=/tmp/ytm_mpv.log`) se o `mpvctl ping` falhar;
  `--vo=null` evita o hang no teardown do wayland ao dar `quit`; espera o socket;
- `stop_music()` — `mpvctl stop` (quit graceful pelo socket), espera até ~2s o
  ping falhar, só então `kill -9` nos mpv que **não** são
  `mpvpaper`/`unique-wallpaper-process`; mata a bridge via pidfile,
  `lyrics-panel-toggle close`, remove o socket;
- `pick_from_helper <cmd>...` — roda o helper; erro → notificação crítica;
  rofi com `LINES_FILE`; resolve o id pelo número de linha do `TSV_FILE`;
  **imprime `TITLE\tID` na stdout** (subshell-safe);
- `pick_destination(<url>, <título>)` — submenu de destino ao escolher uma
  faixa: **Tocar agora** → `play_url`; **Adicionar à fila** →
  `mpvctl load <url> append <título>` (spawn do daemon se preciso) + notifica
  "Na fila: …"; usado por Search, Liked e "Pick a song";
- `play_url(<url>, <título>)` — se `mpvctl ping` falhar → `spawn_mpv_idle()`;
  `mpvctl load <url> replace` (loadfile — **não mata o daemon**) + `mpvctl
  title "<título>"` (media-title, sem sufixo ` (m:ss)`) + `open_panel()` +
  `lyrics-panel-toggle open`;
- `queue_loop()` / `queue_shuffle()` / `queue_view()` / `queue_menu()` —
  submenu 🎛️: `loop-file`/`loop-playlist`, `shuffle`, e a lista da fila no
  rofi (`mpvctl queue`); ao escolher uma faixa, submenu de ação **tocar
  agora** (`play`), **tocar a seguir** (`move` — `playlist-move` para a
  posição logo após a atual) ou **remover da fila** (`remove` —
  `playlist-remove`; remove/reordena reabrem a lista em cadeia); **Limpar
  fila** (`clear` — `playlist-clear`);
- `open_panel()` — spawna o hyprwave se ausente; spawna a bridge se o
  pidfile estiver morto; espera o namespace `hyprwave` aparecer no
  `hyprctl layers` (3 misses consecutivos ≈ 0.6s → `hyprwave-toggle
  visibility`); **respeita `/tmp/ytm_panel_hidden`** (estado manual);
- `nowplaying()` — removida (a entrada "🎧 Now Playing" saiu do menu; o
  painel abre sozinho ao tocar via `open_panel()`);
- `toggle_panel()` — chama `hyprwave-panel-toggle` + notifica o estado;
- `lyrics_menu()` — submenu 🎤 (visibility + 3 tamanhos via
  `lyrics-panel-toggle`);
- `reload_cookies()` — `refresh_auth.py --list-accounts`; com 2+ contas
  abre o **seletor** (rofi, `•` = preferida), grava `account_pref`; depois
  regenera os headers e notifica a conta ativa;
- `search_music()` / `liked_music()` / `playlists_music()` — fluxos do menu
  (submenu "Play whole playlist" / "Pick a song" nas playlists).

**Menu principal** (8 entradas, `case` exato): 🔎 Search · ❤️ Liked ·
📁 My Playlists · 🎛️ Fila e Reprodução · 🎤 Letras · 👁️ Mostrar/Esconder
Painel · ⏹ Parar Música · 🔄 Recarregar Cookies. Ao selecionar uma faixa,
o submenu de destino decide entre tocar agora e enfileirar.

**Contrato do helper (stdout/stderr):** sucesso → uma linha por item + grava
TSV/LINES; erro → mensagem pt-BR no **stderr** + JSON no stdout + exit 1.

### 2.2 `ytm.py` — helper da API

**Comandos:**

| Comando | Chamada ytmusicapi | Limite | Filtro |
|---|---|---|---|
| `search <query>` | `yt.search(q, filter="songs")` | 20 | só músicas |
| `liked` | `yt.get_liked_songs()` | 100 | faixas com `videoId` |
| `playlists` | `yt.get_library_playlists()` | ilimitado | todas |
| `playlist <id>` | `yt.get_playlist(pid)` | 200 | faixas com `videoId` |

- `get_client()` — headers de `YTM_HEADERS` (env) ou `headers_auth.json`;
- `main()` — **auto-recuperação**: exceção → `refresh_auth()` → retry 1x;
- `emit()` — grava TSV (`i\tid`) + LINES e imprime `Título - Artistas (dur)`.

**Env:** `YTM_HEADERS`, `YTM_PYTHON`, `YTM_PROFILE`.

### 2.3 `refresh_auth.py` — credencial (fluxo completo em `03-authentication.md`)

1. Lê cookies do Firefox (perfil snap) com `browser-cookie3`;
2. Descarta rastreio; valida `SAPISID`/`__Secure-3PAPISID`;
3. `DATASYNC_ID` da página do YT Music (logada);
4. `SAPISIDHASH`/`1PHASH`/`3PHASH` (`sha1("{datasync_id} {t} {sapisid} https://www.youtube.com")`);
5. **Probe de authuser 0..4** (valida com `get_liked_songs`, rotula com
   `get_account_info`) — o endpoint `account/accounts_list` não enumera
   multi-login; `--list-accounts` imprime as contas; `account_pref`/
   `YTM_AUTHUSER` fixam a preferida;
6. Grava `headers_auth.json` (tmp → `chmod 600` → `os.replace`).

### 2.4 `mpvctl.py` — cliente IPC do mpv

Comandos: `get` (estado completo, tolerante por propriedade), `toggle`,
`stop` (quit + unlink socket, graceful), `vol ±N|N`, `seek S`,
`next`/`prev` (`playlist-next`/`playlist-prev`), `load <url> <replace|append>`
(`loadfile`/`append-play` — usado pelo daemon), `title <texto>`
(`set_property force-media-title` — `media-title` é read-only no IPC),
`loop <off|track|playlist>` (`loop-file`/
`loop-playlist`), `shuffle <on|off>`, `queue` (playlist completa como TSV,
com nomes resolvidos pelo registry/caches), `play <idx>` (`playlist-pos`),
`remove <idx>` (`playlist-remove`), `move <idx>` (`playlist-move` para a
posição logo após a atual — "tocar a seguir"), `clear`, `playlist`
(`{count, pos}`), `ping`
(`get_property filename` — exit 1 se o daemon estiver vivo mas sem faixa).
Stdlib apenas; respostas JSON linha a linha; timeout 2s.

### 2.5 `mpris_bridge.py` — player MPRIS próprio

- Nome no bus: `org.mpris.MediaPlayer2.ytm` (o mpv tem MPRIS nativo em
  `.mpv`, mas **sem customização** — sem título real, sem artUrl, sem
  next/prev; por isso a bridge);
- **Conexão persistente** ao socket do mpv com `observe_property`
  (media-title, pause, volume, filename, playlist-count, playlist-pos);
  reage a eventos `property-change`/`end-file`/`playback-restart`/`seek`.
  Única poll: `time-pos` + `duration` a cada 1s na **mesma conexão** (não
  spawna mais `mpvctl.py` a cada 0.5s);
- expõe 15 propriedades (PlaybackStatus — `Stopped` quando o daemon está
  ocioso sem faixa, com um **grace period de 3s** (STOPPED_GRACE) para não
  desligar os painéis na transição entre faixas; Metadata com
  `xesam:title`/`xesam:artist`/
  `mpris:length`/`mpris:trackid`/`mpris:artUrl`, Position, Volume,
  CanGoNext/CanGoPrevious — `true` só com playlist) e métodos
  Play/Pause/PlayPause/Stop/Next/Previous/Seek/SetPosition + signal `Seeked`;
- `artUrl` = `https://i.ytimg.com/vi/<id>/hqdefault.jpg` — **sempre a capa
  da faixa** (o yt-dlp enriquece title/artist, mas a arte é forçada para o
  hqdefault do vídeo, não a thumbnail do álbum/playlist); o hyprwave baixa
  sozinho, sem cache local; o `mpris:trackid` é **sanitizado** (`_tid()`)
  porque object path D-Bus só aceita `[A-Za-z0-9_]` — vids com `-`/`_`
  (ex.: `jAtLL-JTBVw` → `/ytm/jAtLL_JTBVw`) derrubavam a bridge inteira;
- **Fallback de vid**: quando o `filename` do mpv é o URL de stream já
  resolvido (caso fila/playlist, sem `?v=`), a bridge consulta a propriedade
  `playlist` do mpv (request_id 52) e extrai o `vid` da entrada atual —
  a capa/título certo aparecem também tocando desde a fila;
- Título/artista: **seed imediato** do `media-title` do mpv (título real
  extraído pelo próprio mpv/yt-dlp); o yt-dlp `-J` (timeout 60s) é chamado
  só em background quando faltar title/artist; flat-playlist da URL da
  playlist quando disponível;
- **Caches persistentes** em `~/.cache/rofi-ytm/`: `meta.json` (por vid,
  TTL 7 dias) e `playlists.json` (flat-playlist por list_id, TTL 24h);
  atômico (`.tmp` + `os.replace`);
- **Retry automático**: em `end-file` com `reason=error` (403/stall)
  religa a mesma URL 1 vez (backoff 2s) e notifica;
- **Reconexão**: se o socket cair, tenta reconectar por até ~2 min antes de
  sair (sobrevive a restart do daemon); pidfile `/tmp/ytm_bridge.pid`;
  debug rotativo em `/tmp/ytm_bridge_debug.log` (truncado em 1 MB).

### 2.6 `hyprwave-panel-toggle.sh` — toggle do painel

`~/.local/bin/hyprwave-panel-toggle`: spawna o hyprwave se ausente (com
`export PATH="$HOME/.local/bin:$PATH"`), `hyprwave-toggle visibility` e grava
`/tmp/ytm_panel_hidden` conforme o estado final. Chamado pelo menu `👁️` e
pelo keybind `SUPER CTRL Y`.

### 2.7 `lyrics_player.py` — karaokê ANSI (fluxo completo em `08-lyrics-panel.md`)

Lê a bridge via D-Bus (fallback MPRIS nativo do mpv), poll 0.2s; busca no
lrclib (GET → search progressivo → synced/plain/instrumental/none), **cache
persistente por trackid em `~/.cache/rofi-ytm/lyrics.json` (TTL 7 dias)** —
músicas repetidas não rebuscam o lrclib; render ANSI adaptável ao terminal
(`update_terminal_size`, SIGWINCH, `LYRICS_COLS`/`LYRICS_ROWS` para teste),
quebra por palavra inteira, espaçamento inteligente (1 vazia entre versos);
sai sozinho quando o mpv morre (~4s).

### 2.8 `lyrics-panel-toggle.sh` — controle da janela de letras

`~/.local/bin/lyrics-panel-toggle`: ações `visibility|open|close|size
compacta|media|grande` (420×300 / 600×400 / 800×600); pidfile
`/tmp/ytm_lyrics.pid`; janela via `kitty --class ytm-lyrics --title "Letras"`
(sem `focuswindow` — display-only); resize via `hyprctl dispatch
resizewindowpixel exact W H,address:<addr>`.

---

## 3. Dependências

### 3.1 Sistema (distro base do instalador)

| Pacote | Uso |
|---|---|
| `rofi` | menus (1.7.8+wayland1) |
| `mpv` | player (0.41.0) |
| `libnotify` (`notify-send`) | notificações |
| `git`, `curl`, `node`, `npm` | provider/deno/instalação |
| `python3` + `venv` | helpers |
| `libgtk4-layer-shell-dev` | build do hyprwave (só com `--hyprwave`) |

### 3.2 Python (venv `~/.local/share/ytm-venv`)

| Pacote | Versão | Uso |
|---|---|---|
| `ytmusicapi` | 1.12.2 | API YouTube Music |
| `browser-cookie3` | 0.20.1 | cookies do Firefox |
| `yt-dlp` | 2026.07.04 | extração/streaming (mpv usa pelo PATH) |
| `bgutil-ytdlp-pot-provider` | 1.3.1 | PO Token (plugin pip) |
| `dbus-next` | 0.2.3 | bridge MPRIS + player de letras |

### 3.3 Externas / runtime

| Item | Papel |
|---|---|
| `deno` (~/.deno) | runtime JS do yt-dlp (assinaturas + PO token) |
| `~/bgutil-ytdlp-pot-provider` | provider binário (clone + `npm ci`) |
| **Hyprwave** v1.1 (`~/.local/bin/hyprwave`) | painel "Now Playing" (build patched) |
| `hyprwave-toggle` | controle por sinais |
| lrclib.net | fonte de letras (API aberta, sem auth) |
| kitty | terminal do painel de letras |
| PipeWire-pulse | sink de áudio + monitor do visualizer |

### 3.4 Hyprwave — patches aplicados no build (`src/hyprwave/*.patch`)

O `install.sh` clona `shantanubaddar/hyprwave`, aplica **todos os `*.patch`
em ordem alfabética** (art → jitter → reconnect) e roda
`make all && PREFIX=$HOME/.local make install`.

| Patch | Arquivos | O que faz |
|---|---|---|
| `hyprwave-art.patch` | `art.c`, `notification.c` | proporção da capa (COVER, sem espremer) + layout da notificação (70×70, alinhada, com overflow hidden) |
| `hyprwave-jitter.patch` | `visualizer.c`, `visualizer.h` | ondas estáveis: ring buffer de 2048 amostras por passada RMS (antes ~18/bin), `SMOOTHING_FACTOR=0.85`, `fragsize=8192`, 32 barras full-width, container no rodapé (`size_request(-1, 24)`) — painel volta a ~354×32 |
| `hyprwave-reconnect.patch` | `main.c` | re-seleciona o player MPRIS preferido quando qualquer player novo aparece; **+ fix do congelamento**: capa/ícone só recarregam na troca de faixa/estado (antes recarregava a cada `PropertiesChanged` ~2x/s — download HTTP síncrono travava o main loop do GTK e o render de 60fps); **+ visualizer empilhado** abaixo da control bar (VBox) em vez de overlay sobre os botões |

---

## 4. Integrações e comunicação

### 4.1 IPC mpv (socket JSON)

- `--input-ipc-server=/tmp/mpv-ytm.sock`; socket antigo é removido antes do
  spawn do daemon; comandos: `{"command": ["get_property", ...]}` etc.;
  respostas JSON linha a linha (Newline-delimited);
- **Eventos**: a bridge mantém uma conexão persistente e usa
  `observe_property` (ids próprios) + eventos `property-change`/`end-file`/
  `playback-restart`/`seek`; o `ping` do mpvctl usa `get_property filename`
  (exit 1 se o daemon estiver vivo mas sem faixa — idle);
- propriedades de **arquivo** (time-pos/duration/media-title) só respondem
  após o buffer do yt-dlp (8–30s); a bridge faz poll só de `time-pos` +
  `duration` a cada 1s na mesma conexão.

### 4.2 D-Bus MPRIS

- `org.mpris.MediaPlayer2.ytm` (bridge) + `org.mpris.MediaPlayer2.mpv`
  (nativo, fallback). `playerctl -p ytm` / `gdbus` para testar;
- hyprwave `preference = ytm,mpv,spotify,vlc` → bridge primeiro;
- dbus-next: getters precisam dos nomes exatos das props e retornar valores
  **raw** (o dbus-next re-embrulha em Variant); `MessageType.METHOD_RETURN`
  é enum (2), não int.

### 4.3 Sinais (hyprwave-toggle)

| Ação | Sinal |
|---|---|
| visibility | SIGUSR1 |
| expand | SIGUSR2 |
| play | SIGRTMIN |
| next / prev | SIGRTMIN+1 / +2 |

### 4.4 Hyprland (configs tocadas pelo instalador, idempotente)

- `Keybinds.conf`:
  - `bindd = $mainMod SHIFT, Y, YouTube Music, exec, $UserScripts/RofiYtm.sh` (launcher);
  - `bindd = $mainMod CTRL, Y, Toggle YTM panel, exec, $HOME/.local/bin/hyprwave-panel-toggle`;
  - `bindd = $mainMod CTRL, L, Toggle YTM lyrics, exec, $HOME/.local/bin/lyrics-panel-toggle visibility`;
- `WindowRules.conf` (block v3):
  - `windowrule { name = ytm lyrics; match:class = ^(ytm-lyrics)$; float = on; size = 420 300; move = 1155 42; pin = on; no_initial_focus = on; no_focus = on }` (nota: sintaxe `windowrule { ... }` é a hyprlang v3; `no_border` não é aceito no one-liner);
- `hyprctl layers -j`: painel = namespace `hyprwave` (nível 2), notificação = `hyprwave-notification` (nível 3); grep `'"namespace": "hyprwave"'` diferencia;
- keybind do launcher também existe em `system_keybinds.lua` (`SUPER SHIFT Y`).

### 4.5 Repositórios git envolvidos

| Repo | Papel |
|---|---|
| `anomalyco/rofi-ytm` (este) | fontes + instalador + docs |
| `shantanubaddar/hyprwave` (v1.1, clone em /tmp no build) | painel (patched) |
| `Brainicism/bgutil-ytdlp-pot-provider` | PO Token provider (`~/bgutil-ytdlp-pot-provider`) |
| `sabymarqy-ship-it/C-DIGO-BASE-PARA-A-LYRICS` | referência do karaokê ANSI (não é dependência runtime) |

### 4.6 APIs externas

| API | Uso | Auth |
|---|---|---|
| YouTube Music (ytmusicapi) | busca/curtidas/playlists | headers do navegador (SAPISIDHASH) |
| googlevideo CDN | stream de áudio | `pot=` (PO Token) + cookies |
| lrclib.net (`/api/get`, `/api/search`) | letras | nenhuma |
| D-Bus session bus | MPRIS | — |
| PulseAudio monitor | visualizer | — |

---

## 5. Instalação (passo a passo)

### 5.1 Fluxo do `install.sh`

1. **Deps do sistema** (sudo, por distro: apt/pacman/dnf) — só o que falta;
2. **venv** (`--prefix`, default `~/.local/share/ytm-venv`) + pip
   (ytmusicapi, browser-cookie3, yt-dlp, bgutil-ytdlp-pot-provider,
   dbus-next);
3. **deno** (script oficial → `~/.deno`);
4. **Provider bgutil**: clone + `npm ci --frozen-lockfile` + **warmup**
   (`generate_once.ts --version` — a 1ª execução baixa deps do deno e pode
   estourar o timeout de 15s do plugin);
5. **Perfil Firefox**: `--profile`/`YTM_PROFILE` → snap → nativo → flatpak;
6. **Deploy** (de `src/`):
   - `ytm.py`, `refresh_auth.py` (sed `__FIREFOX_PROFILE__`), `mpvctl.py`,
     `mpris_bridge.py` (sed), `lyrics_player.py` → `$CONFIG_DIR/rofi/scripts/ytm/`;
   - `RofiYtm.sh` (sed 4 placeholders: `__VENV_DIR__`, `__DENO_DIR__`,
     `__CONFIG_DIR__`, `__FIREFOX_PROFILE__`) → `$CONFIG_DIR/hypr/UserScripts/`
     (ou `~/.local/bin`);
   - `hyprwave-panel-toggle.sh`, `lyrics-panel-toggle.sh` (sed
     `__VENV_DIR__`/`__DENO_DIR__`/`__CONFIG_DIR__`) → `~/.local/bin/`;
   - fallbacks: sem temas Beats → remove `-config`; sem ícone → notif sem `-i`;
7. **Bootstrap de auth** (`refresh_auth.py`, não-fatal);
8. **Keybinds/windowrules** (`setup_toggle_keybind` + `setup_lyrics_bindings`,
   idempotentes — grep antes de append; remoção no uninstall via sed);
9. **`--hyprwave`** → `install_hyprwave()`: apt `libgtk4-layer-shell-dev`,
   clone, aplica os 3 patches, `make` + `PREFIX=~/.local make install`,
   gera `~/.config/hyprwave/config.conf` se ausente;
10. **Verificação** (`--skip-verify` pula): busca de teste + extração com
    `pot=` na URL.

### 5.2 Opções

| Flag | Efeito |
|---|---|
| `--profile <dir>` | perfil Firefox (pula auto-detecção) |
| `--prefix <dir>` | venv (default `~/.local/share/ytm-venv`) |
| `--config-dir <dir>` | onde deploya (default `~/.config`) |
| `--no-deps` | sem sudo |
| `--skip-verify` | pula verificação final |
| `--uninstall` | remove tudo + keybinds/windowrules + pidfiles |
| `-h / --help` | ajuda |

Env: `YTM_PROFILE`, `YTM_VENV`, `YTM_CONFIG_DIR`, `YTM_PROVIDER_DIR`,
`DENO_INSTALL`.

### 5.3 Verificação pós-instalação

```bash
# auth + busca (20 linhas "título - artista (duração)")
$VENV/bin/python ~/.config/rofi/scripts/ytm/ytm.py search "pink floyd"
# plugin PO token
$VENV/bin/yt-dlp -v 2>&1 | grep -i "PO Token"
# extração com pot=
$VENV/bin/yt-dlp -f bestaudio/best -g \
  --extractor-args "youtube:player_client=web_music" \
  --remote-components ejs:github \
  --cookies-from-browser "firefox:<perfil>" '<watch url>'
# painel
~/.config/hypr/UserScripts/RofiYtm.sh   # prova real pela UI
```

---

## 6. Ambiente do autor (onde este sistema roda)

> Registro do sistema real usado durante todo o desenvolvimento — útil como
> referência de compatibilidade e reprodução.

### Sistema e compositor

| Item | Versão |
|---|---|
| Distribuição | **Ubuntu 26.04 LTS** |
| Compositor | **Hyprland 0.56.2** (commit `efb509937`, v0.56.2) |
| Monitor | eDP-1 1920×1080 (Painel hyprwave ~782,42 354×32; letras 1155,42 420×300) |
| Terminal | kitty 0.48.2 (TERM=xterm-kitty) |
| Shell | zsh (aliases `rtk`) |

### Ferramentas e libs

| Item | Versão |
|---|---|
| rofi | 1.7.8+wayland1 (temas `config-rofi-Beats*.rasi` — KoolDots/Beats, em `~/.config/rofi/`) |
| mpv | 0.41.0 |
| yt-dlp | 2026.07.04 (venv) |
| deno | 2.9.5 (x86_64-unknown-linux-gnu, `~/.deno/bin`) |
| Python | 3.14.4 (sistema e venv) |
| node / npm | v22.22.1 / 9.2.0 |
| playerctl | v2.4.1 |
| waybar | v0.15.0 |
| swaync | 0.12.4 |
| gtk4 | 4.22.4 |
| libgtk4-layer-shell | 1.3.0-1 (`pkg-config gtk4-layer-shell-0` = 1.3.0) |
| PipeWire-Pulse | protocolo 35 |
| Firefox | **snap** — perfil `~/snap/firefox/common/.mozilla/firefox/2b11ppm1.default` |

### venv (`~/.local/share/ytm-venv`)

| Pacote | Versão |
|---|---|
| ytmusicapi | 1.12.2 |
| browser-cookie3 | 0.20.1 |
| dbus-next | 0.2.3 |
| bgutil-ytdlp-pot-provider | 1.3.1 |
| yt-dlp | 2026.7.4 |

### Hyprwave

- Clone de build: `shantanubaddar/hyprwave`, último commit `cd1c663`
  ("Update version in README to v1.1" → **v1.1**);
- Binário: `~/.local/bin/hyprwave` (sem `--version`); fonte VT323 em
  `~/.local/share/fonts/hyprwave/`;
- `~/.config/hyprwave/config.conf`:
  `[General] edge=top margin=10 layer=top exclusive_zone=0;
   [Notifications] enabled=true now_playing=true;
   [Visualizer] enabled=true idle_timeout=5;
   [VerticalDisplay] enabled=false idle_timeout=5;
   [MusicPlayer] preference=ytm,mpv,spotify,vlc`

### Hyprland — keybinds e rules atuais

```conf
# Keybinds.conf
bindd = $mainMod SHIFT, Y, YouTube Music, exec, $UserScripts/RofiYtm.sh
bindd = $mainMod CTRL, Y, Toggle YTM panel, exec, /home/enosh/.local/bin/hyprwave-panel-toggle
bindd = $mainMod CTRL, L, Toggle YTM lyrics, exec, $HOME/.local/bin/lyrics-panel-toggle visibility

# WindowRules.conf
windowrule {
    name = ytm lyrics
    match:class = ^(ytm-lyrics)$
    float = on
    size = 420 300
    move = 1155 42
    pin = on
    no_initial_focus = on
    no_focus = on
}
```

- `~/.config/hypr/UserScripts/`: 00-Readme, RainbowBorders-low-cpu.sh,
  RofiBeats.sh, RofiCalc.sh, **RofiYtm.sh**, Weather*.sh/py, WeatherWrap.sh;
- Integração RofiBeats: item "Play from YouTube Music 🎧" → delega ao
  `RofiYtm.sh`;
- `~/.config/swaync/icons/music.png` (ícone das notificações).

### Riscos/notas do ambiente

- Firefox snap: o perfil é o que o `refresh_auth.py` e o `--cookies-from-browser`
  usam; se trocar de conta, `🔄 Recarregar Cookies` (seletor multi-conta);
- mpv do ambiente morre com stall do stream `web_music` ocasionalmente —
  comportamento conhecido, a bridge sai junto (por design);
- O PATH do Hyprland **não** inclui `~/.local/bin` — por isso o launcher e
  os toggles fazem `export PATH="$HOME/.local/bin:$PATH"` no topo.
