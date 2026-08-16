# 06 — História do projeto (jornada e decisões)

Este documento registra o raciocínio por trás de cada escolha — serve para
entender **por que** o sistema é como é, e para não repetir becos sem saída.
As fases iniciais (1–6) descrevem a criação; as fases 7+ cobrem o painel, a
bridge e as letras.

---

## Fase 1 — Análise do contexto (o que não servia)

Os dotfiles usam Hyprland (KoolDots/LinuxBeginnings) com **rofi-beats** já
configurado. O protótipo original `rofi-ytm` (rofi-blocks) dependia de um fork
do rofi com o modi `blocks` — a build instalada (`/usr/local/bin/rofi`) é a
1.7.8+wayland1 **sem** esse modi, e trocar o rofi quebraria os temas.
Alternativas web pesquisadas (QuickMedia, youtube-viewer, ytdl-mpv) **não
acessam a conta** do YouTube Music — todas descartadas.

**Decisão:** `rofi -dmenu` encadeado + `ytmusicapi` + `mpv`.

## Fase 2 — OAuth: tentado, abandonado por bug do Google

- Client "Desktop app" no Google Cloud → `invalid_client` no device flow
  (Google restringiu o tipo; só "TV and Limited Input devices" funciona);
- Client TV → device flow funcionou, `oauth.json` gravado;
- **Porém:** toda chamada da API → HTTP 400 "Request contains an invalid
  argument" — bug conhecido (`sigma67/ytmusicapi#813`, ainda aberta). O
  workaround oficial é browser headers.

**Decisão:** abandonar OAuth; `get_client()` 100% browser headers.

## Fase 3 — Headers manuais e as armadilhas do paste

1. A primeira linha do painel de rede (`POST /youtubei/... HTTP/3`) vira
   chave lixo no JSON → 400. **Remover.**
2. `content-encoding: gzip` é header de **resposta** → deixa o servidor
   esperando body gzip. **Remover.**
3. Chaves do JSON são **minúsculas** — `json.load(...)['Cookie']` dá len 0.

**Decisão:** chaves minúsculas, sem `POST ... HTTP/3`, sem content-encoding.

## Fase 4 — Automação da auth: cookies do Firefox + SAPISIDHASH

Surgiu o `refresh_auth.py`: `browser-cookie3` lê o perfil **snap** do
Firefox; descarta rastreio (~2.5k chars finais); descobre o `DATASYNC_ID` do
`ytcfg` da página logada; gera o SAPISIDHASH:

```
sha1(f"{datasync_id} {int(time.time())} {sapisid} https://www.youtube.com")
```

(validado empiricamente depois de tentativas frustradas com ms, hmac e
origin music.youtube.com). Auto-recuperação no `ytm.py`: exceção → refresh →
1 retry. Mensagens de erro em pt-BR (3 níveis).

## Fase 5 — A saga do 403 (PO Token)

"Algumas tocam e outras não": mpv vivo com 0% CPU, `[ffmpeg] https: HTTP
error 403 Forbidden`. URLs boas e ruins tinham parâmetros idênticos; só
faltava **`pot=`** (GVS PO Token exigido para clientes web em 2026).
Componentes na ordem: **deno** (runtime JS), **yt-dlp via pip no venv**
(o apt congela em 2026.3.17), **bgutil-ytdlp-pot-provider** (plugin +
clone + `npm ci`; modo script-deno). O `play_url()` final combina
`web_music` + `ejs:github` + cookies do perfil snap → **12/12 playbacks**.

## Fase 6 — Limpezas

| Removido | Motivo |
|---|---|
| `client_creds.json`, `oauth.json`, `device_flow.py` | código morto do OAuth abandonado |
| `auth.py` (modo manual) | ninguém referenciava |
| `__pycache__/` | bytecode lixo |
| symlink `𝜋thon` no venv/bin | arquivo acidental |
| pasta `rofi-ytm` original (com .git) | protótipo rofi-blocks substituído |

## Fase 7 — Conta free e multi-conta

- Verificação empírica com conta **sem Premium**: o pipeline nunca toca
  anúncios (yt-dlp não expõe formatos `ad`); a qualidade cai para 128 kbps
  (itag 251/opus vs 256 kbps AAC premium); PO Token funciona igual;
- Bug encontrado: `x-goog-authuser` **hardcoded** ("2") no refresh — após
  trocar de conta, liked/playlists respondiam como deslogado. Diagnóstico:
  probe de authuser 0..4 → a conta ativa é a de índice 0;
- **Multi-login**: com 2+ contas no Firefox, os cookies valem para todas —
  quem seleciona é o header. O endpoint `account/accounts_list` **não
  enumera** multi-login (só a conta da sessão atual) → a enumeração virou
  probe (authuser 0..4 + validação com `get_liked_songs` + rótulo com
  `get_account_info`);
- Menu ganhou **🔄 Recarregar Cookies**: seletor de contas (rofi, `•` =
  preferida), grava `account_pref`; env `YTM_AUTHUSER` tem o mesmo efeito;
  conta inválida → fallback para a primeira válida.

## Fase 8 — O painel: 3 tentativas (eww → AGS → Hyprwave)

O pedido original era um painel com progresso, volume, stop e ondas. Três
caminhos foram tentados:

### 8.1 eww (Elkowar's Wacky Widgets) — ABANDONADO

- rofi 1.7.8 **não tem** refresh-delay (async é append-only) → painel
  ao vivo impossível no rofi; eww 0.6.0 instalado;
- **Bug do build**: `deflisten`/`defpoll` NUNCA iniciavam (reproduzido em
  config mínima e na config real do usuário) — pivot para `defvar` +
  `eww update` externo (funciona, mas é atômico e rejeita valores inválidos);
- cava deste sistema **não tem suporte pipewire** → fallback pactl
  (null-sink + loopback) obrigatório;
- Funcionou, mas com muito atrito. **Decisão:** abandonar o eww.

### 8.2 AGS v1 (Aylur's GTK Shell) — ABANDONADO

- AGS 1.9.0 já instalado no sistema; janelas layer via GJS/Gtk4;
- **Root causes corrigidas ao longo do debug**: (1) monitor morria antes do
  mpv subir (faltava sleep no ping-falho — grace 120s); (2) deploy sem sed
  deixava `__PANEL_DIR__` literal; (3) cava `data_format=ascii` separa por
  `;` (não espaço);
- E2E 15/15 e verificação ao vivo OK — mas o usuário **pivotou** para o
  Hyprwave ("esqueça, quero substituir isso pelo hyprwave que já é um painel
  de controle pronto"). **Decisão:** abandonar o AGS (painel custom removido).

### 8.3 Hyprwave (escolhido)

- shantanubaddar/hyprwave v1.1 — painel pronto, MPRIS + visualizer próprio;
- Construído via `install.sh --hyprwave` (apt `libgtk4-layer-shell-dev` +
  clone + patches + `make`); instalado em `~/.local/bin`;
- **Hyprwave não roda quando o launcher spawna** → causa: o PATH do Hyprland
  não tem `~/.local/bin` → `export PATH="$HOME/.local/bin:$PATH"` no topo
  do launcher e dos toggles;
- **Painel não aparece de primeira** (toggle incondicional escondia o painel
  recém-nascido) → detecção por `hyprctl layers` com 3 misses consecutivos;
- **Esconder/mostrar manual**: menu `👁️` + keybind `SUPER CTRL Y` via
  `hyprwave-panel-toggle` + flag `/tmp/ytm_panel_hidden` — o `open_panel`
  respeita o estado manual.

### Patches do Hyprwave (a cada bug, um patch)

1. `hyprwave-reconnect.patch` — o hyprwave ficava preso no MPRIS nativo do
   mpv quando a bridge aparecia depois; `on_player_name_changed` agora
   re-avalia a preference a cada player novo;
2. `hyprwave-art.patch` — arte 16:9 espremida em 120×120 (FALSE →
   preserve_aspect) + capa da notificação imensa (pixbuf nativo estourava a
   janela layer) → size*2 com escala + alignment/overflow no widget;
3. `hyprwave-jitter.patch` — ondas pulavam: RMS com ~18 amostras/bin e
   smoothing 0.7 insuficientes → ring buffer de 2048 amostras (37–64/bin),
   `SMOOTHING_FACTOR=0.85`, `fragsize=8192`, 32 barras full-width (escolha
   do usuário), container limitado ao rodapé (`size_request(-1, 24)`) —
   painel volta ao tamanho original (~354×32);
4. (no reconnect.patch) **Ondas congelavam com música tocando** — capa do
   álbum (download HTTP **síncrono** no main thread GTK) e ícone de
   play/pause recarregavam a **cada** `PropertiesChanged` (~2x/s) →
   passaram a recarregar só na troca de faixa/estado. Instrumentado com
   contadores (update_calls_persec oscilava 1↔48 com o spam `Icon found`
   no log; pós-fix 62 sólido);
5. (no reconnect.patch) **Ondas fora da "caixa"** — visualizer era overlay
   sobre a control bar e preenchia tudo (FILL/hexpand) → empilhado num VBox
   abaixo da control bar (com fix de tamanho 275px centrado no rodapé,
   igual ao vanilla — experimento de padding foi testado e **revertido** a
   pedido do usuário);
6. `setup_lyrics_bindings` corrigiu a **windowrule** que usava
   `no_border` no one-liner (invalid field type) → bloco v3
   `windowrule { match:class ... float/size/move }` (o usuário pediu
   "deixa a borda" — sem `no_border`).

## Fase 9 — Bridge MPRIS (por que não usar a nativa)

O mpv 0.33+ tem MPRIS nativo (`org.mpris.MediaPlayer2.mpv`) — uma bridge
python foi escrita e **descartada** quando se descobriu isso. Porém o
pedido seguinte foi: **título real, thumbnail no painel e botões de
próxima/anterior em playlists**. O MPRIS nativo não permite nenhum dos
três (sem opção de config; título = media-title; sem artUrl; next/prev
sempre desabilitados). A bridge voltou:

- Nome próprio `org.mpris.MediaPlayer2.ytm` + `preference = ytm,mpv,...`;
- Título real: launcher passa `--force-media-title` (sem sufixo ` (m:ss)`),
  bridge completa com yt-dlp `-J`/flat-playlist quando vazio;
- Thumbnail: `mpris:artUrl = https://i.ytimg.com/vi/<id>/maxresdefault.jpg`
  (hyprwave baixa sozinho — sem cache em disco; descobriu-se que o padrão
  de URL funciona para ids reais);
- Next/Prev: mpv tocando a URL da playlist inteira expande tudo; `mpvctl
  next|prev|playlist` (IPC `playlist-next`/`playlist-prev`); `CanGoNext/
  CanGoPrevious` controlados por `pl_pos/pl_count` → botões habilitados só
  em playlist;
- **Root causes do debug da bridge**: (1) `ydlp_args()` esquecia o binário
  (`FileNotFoundError` no spawn); (2) yt-dlp `-J` da watch URL é lento
  (>60s) → timeout; **solução**: art sempre pelo padrão i.ytimg (imediato)
  e title/artist via flat-playlist da playlist (cache por list_id);
- dbus-next: getters com nome exato das props, retorno **raw** (re-embrulha
  em Variant), `MessageType` é enum (METHOD_RETURN=2), `dbus_property`
  (não `property_`), `PropertyAccess.READ` em tudo.

## Fase 10 — Painel de letras (karaokê ANSI)

Pedido: usar o repo `sabymarqy-ship-it/C-DIGO-BASE-PARA-A-LYRICS` num
painel secundário com abrir/fechar por keybind e menu. Decisões do usuário:
fonte **lrclib.net** (sync com fallback plain), **abre junto** com a música,
**fecha no stop**, keybind `SUPER CTRL L`, janela float à direita do painel
(1155,42), 3 tamanhos via menu.

- `lyrics_player.py`: poll 0.2s no MPRIS da bridge; lrclib GET →
  fallback search progressivo (`[title artist]` → `[title]`, primeira com
  `syncedLyrics`); cache por trackid; karaokê ANSI (linha ativa em bold,
  inativas em cinza);
- **Root causes**: `MessageType` enum (viave do player); `ydlp_args` com o
  binário no início; fetch de faixa única lento (aceito com timeout 60s);
- **Layout**: palavras quebradas ("ba"/"by") — TEXT_WIDTH fixo 60 não
  acompanhava a janela compacta → ajuste ao terminal real (`SIGWINCH`,
  `LYRICS_COLS/ROWS` para teste), quebra por palavra inteira, espaçamento
  inteligente (verso quebrado em linhas consecutivas + exatamente 1 vazia
  entre versos — `LINE_GAP` fixo causava "tocadas" ou 2 vazias);
- **Janela presa no workspace** → `pin = on` + `no_initial_focus` +
  `no_focus` na windowrule (janela display-only que nunca rouba foco e
  acompanha o painel em todos os workspaces);
- **Notificação redundante removida** — o launcher não notifica mais "Now
  Playing" (o hyprwave tem a própria).

## Fase 11 — Documentação reestruturada (atual)

O usuário pediu a reestruturação completa da documentação: README como
apresentação; overview com todas as funcionalidades; architecture com toda
a arquitetura, dependências, repos, comunicação e o **ambiente do autor**
(versões: Ubuntu 26.04 LTS, Hyprland 0.56.2, rofi 1.7.8+Beats dots, mpv
0.41, kitty 0.48.2, deno 2.9.5, yt-dlp 2026.07.04, Python 3.14.4, venv
1.12.2/0.20.1/0.2.3/1.3.1, playerctl 2.4.1, waybar 0.15, swaync 0.12.4,
gtk4 4.22.4, libgtk4-layer-shell 1.3.0, node 22.22.1, PipeWire proto 35);
docs únicos e profundos por parte (03 auth, 04 playback, 07 painel, 08
letras); 05 troubleshooting por área; 06 history com este histórico.

---

## Lições gerais (para não repetir)

1. **Nunca** `pkill -f` com padrão presente na própria linha de comando do
   shell (mata o shell). Use `pkill -x mpv` / `pgrep -x` / `[p]attern`.
2. Ao refatorar `ytm.py`, verifique o guard `if __name__ == "__main__": main()`.
3. `mpv --no-terminal` suprime o log inteiro — para depurar use
   `--msg-level=all=status`.
4. `grep -nFx` (literal + linha inteira) para casar a escolha do rofi com o
   arquivo de linhas (acentos/emoji seguros).
5. Plugins pip do yt-dlp só valem para o yt-dlp **daquele Python** (venv).
6. `headers_auth.json` é segredo: chmod 600, nunca vai para git/chat.
7. **Deploy de arquivos com placeholder: SEMPRE sed** no deploy (instalar o
   src cru deixa `__PANEL_DIR__` literal e quebra em silêncio).
8. cava `data_format=ascii` separa valores por `;`, não espaço.
9. Propriedades de arquivo do mpv (time-pos/duration/media-title) só
   respondem após o buffer do yt-dlp; propriedades de opção (pause/volume)
   sempre — `ping` usa `pause`.
10. dbus-next: `dbus_property` (não `property_`), getters com nome exato da
    propriedade, retorno raw (Variant re-embrulhado), `MessageType` enum.
11. `zsh` expande `echo ===` (use `printf`); comandos longos com `setsid &`
    podem pendurar o tool (dividir em chamadas curtas).
12. windowrules do Hyprland: formato bloco `windowrule { ... }` (v3) —
    `no_border` só funciona no bloco, não no one-liner.
13. Painel (layer) aparece em todos os workspaces; janela normal fica no
    workspace onde nasceu → `pin = on` para janelas "sempre visíveis".
