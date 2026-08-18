# 07 — Painel "Now Playing" (Hyprwave + bridge MPRIS)

Ao selecionar uma música, o `RofiYtm.sh` mostra o **Hyprwave** (painel
de controle pronto, shantanubaddar/hyprwave) com: **nome real da
música**, **thumbnail do YouTube** como arte, progresso ao vivo,
controles play/pause/**próxima/anterior (em playlist)**, slider de
volume e **visualizer de ondas** (espectro real via PulseAudio).

```
RofiYtm.sh ──▶ mpv daemon (--idle --input-ipc-server=/tmp/mpv-ytm.sock)
                  │ mpvctl load <url> replace · mpvctl title "<título real>"
                  │ IPC JSON (unix socket, conexão persistente + eventos)
                  │        ▲
                  ▼        │ mpvctl.py (get/load/title/toggle/vol/seek/next/prev/queue)
   mpris_bridge.py ────────┘  (observe_property / property-change / end-file)
      │  D-Bus org.mpris.MediaPlayer2.ytm
      │    xesam:title real · mpris:artUrl (thumbnail https, hyprwave
      │    baixa sozinho) · Posição/Volume · CanGoNext/CanGoPrevious
      ▼
   hyprwave (preference = ytm,mpv,spotify,vlc → bridge primeiro)
```

## Por que uma bridge, se o mpv tem MPRIS nativo?

O mpv 0.33+ registra `org.mpris.MediaPlayer2.mpv` sozinho, mas sem
configuração de metadata: ele não deixa trocar o título (fica
"Youtube Music" quando o stream não tem tag) nem injetar
`mpris:artUrl`, e o Next/Previous fica sempre desabilitado. A bridge
resolve os três:

1. **título real** — o launcher aplica o nome certo via `mpvctl title`
   (`set_property media-title`, com o sufixo de duração ` (m:ss)` removido);
   a bridge o semeia imediatamente no `xesam:title` e ainda consulta o
   yt-dlp (artista) quando faltar alguma coisa;
2. **thumbnail** — a bridge roda `yt-dlp -J` na watch URL da faixa
   atual (1x por id, cache em memória), pega a *maior* thumbnail e a
   expõe como `mpris:artUrl` (URL `https://` — o hyprwave baixa e
   redimensiona sozinho, sem cache em disco);
3. **próxima/anterior** — tocando uma playlist inteira
   (`.../playlist?list=<id>`), o yt-dlp expande todas as faixas no mpv;
   `mpvctl.py next|prev` usa `playlist-next/playlist-prev` do IPC e
   `playlist` devolve `{count, pos}`. A bridge expõe `CanGoNext`/
   `CanGoPrevious` = `true` só quando há próxima/anterior → o hyprwave
   habilita/desabilita os botões. Faixa única → `false` (botões off).

O hyprwave escolhe o player pela `preference` do config
(`ytm,mpv,spotify,vlc`): com a bridge viva, usa a bridge; se a bridge
não estiver (ex.: instalou só o mpv), cai no MPRIS nativo.

### Por que a ordenação das flags no `play_url` importa

Na sequência de `play_url()`, o mpv (com seu MPRIS nativo) sobe **antes** da
bridge. O hyprwave escaneia o bus ao iniciar e ao detectar um player novo
(`NameOwnerChanged`); sem ajustes ele ficaria "preso" no MPRIS nativo do mpv
(título = `media-title`, geralmente "YouTube Music") e nunca trocaria para a
bridge `ytm` quando ela aparecesse.

O `install.sh` aplica o patch `src/hyprwave/hyprwave-reconnect.patch` no
`main.c` do hyprwave antes do `make`: `on_player_name_changed` agora re-avalia
a `preference` a cada player MPRIS novo que ganha dono — quando a bridge
(`org.mpris.MediaPlayer2.ytm`) aparece, o hyprwave troca para ela e o título
real (via `yt-dlp`/flat-playlist) é exibido.

## Componentes (deploy em `$CONFIG_DIR/rofi/scripts/ytm/`)

| Arquivo | Função |
|---|---|
| `mpvctl.py` | cliente do socket JSON do mpv (somente stdlib; `get`, `toggle`, `stop`, `vol ±N/N`, `seek S`, `next`, `prev`, `load`, `title`, `loop`, `shuffle`, `queue`, `play`, `clear`, `playlist`, `ping`) |
| `mpris_bridge.py` | player MPRIS2 `org.mpris.MediaPlayer2.ytm` (dbus-next no venv): **conexão persistente** ao socket do mpv com `observe_property` + eventos (`property-change`/`end-file`/`playback-restart`/`seek`) e poll de `time-pos` a cada 1s na mesma conexão; `emit_properties_changed`; métodos Play/Pause/PlayPause/Stop/Next/Previous/Seek/SetPosition; tenta reconectar por até ~2 min se o daemon reiniciar; retry automático em falha de stream (1x); caches em `~/.cache/rofi-ytm/`; pidfile `/tmp/ytm_bridge.pid` |
| `src/hyprwave/config.conf` | modelo do `~/.config/hyprwave/config.conf` (gerado na instalação; o existente **não** é sobrescrito) — `preference = ytm,mpv,spotify,vlc` |

Dependência Python: `dbus-next` (instalado no venv pelo `install.sh`).

## Instalação do Hyprwave

`install.sh --hyprwave` (ou a opção de menu na instalação padrão):

1. instala `libgtk4-layer-shell-dev` (apt — requer sudo no seu terminal);
2. clona `github.com/shantanubaddar/hyprwave`, aplica os patches de
   `src/hyprwave/*.patch` no `main.c`/`visualizer.c`/`notification.c` e roda
   `make` + `PREFIX=~/.local make install` (binário em `~/.local/bin/hyprwave`):
   - `hyprwave-reconnect.patch`: re-seleciona o player MPRIS preferido quando
     qualquer player novo aparece;
   - `hyprwave-art.patch`: proporção da arte + layout da notificação;
   - `hyprwave-jitter.patch`: ondas estáveis (janela de ~2048 amostras por
     passada RMS + `SMOOTHING_FACTOR=0.85` + `fragsize=8192`) — sem os pulos
     das barras durante a reprodução; as ondas ficam no rodapé da control bar
     (overlay com `size_request(-1, 24)`), mantendo o painel no tamanho
     original (~354×32 colapsado);
3. gera `~/.config/hyprwave/config.conf` com `preference = ytm,mpv,spotify,vlc`
   e visualizer ativo.

Sem o hyprwave, a música toca normalmente — o painel apenas não abre.

## Controle externo (hyprwave-toggle)

O hyprwave não tem D-Bus próprio; o script `hyprwave-toggle` envia
sinais ao processo:

| Ação | Sinal | Uso |
|---|---|---|
| mostrar/esconder | SIGUSR1 | `hyprwave-toggle visibility` |
| expandir | SIGUSR2 | `hyprwave-toggle expand` |
| play/pause | SIGRTMIN | `hyprwave-toggle play` |
| próxima | SIGRTMIN+1 | `hyprwave-toggle next` |
| anterior | SIGRTMIN+2 | `hyprwave-toggle prev` |

Com a música pausada (ou sem música) o painel vira um visualizer idle
(`idle_timeout=5`), com as ondas dançando mesmo parado. (Os botões
próxima/anterior do próprio painel usam o MPRIS da bridge, não os
sinais.)

## Comportamento no rofi-ytm

- Primeira música → mpv sobe como **daemon** (`--idle`) com socket;
  painel abre (spawna o hyprwave se não estiver rodando); a bridge MPRIS é
  spawnada se não estiver viva; `hyprwave-toggle visibility`.
- Tocar outra faixa → `mpvctl load <url> replace` — o daemon **não morre**;
  a bridge só vê a metadata mudar (e o painel não pisca).
- Parar (stop) → `mpvctl stop` (quit graceful); o daemon encerra e a bridge
  sai; **o hyprwave fica aberto no visualizer idle** (não é fechado de
  propósito).
- Não há mais a entrada de menu "🎧 Now Playing": o painel abre sozinho ao
  tocar (`open_panel()`), e para mostrá-lo/escondê-lo manualmente use
  `👁️ Mostrar/Esconder Painel` ou `SUPER + CTRL + Y`.
- Volume/play/seek também funcionam por qualquer cliente MPRIS
  (`playerctl -p ytm position 30`, teclas do Hyprland, etc.).

## Esconder/mostrar o painel

Você pode ocultar o painel (e voltar a mostrá-lo) sem parar a música:

- **Menu RofiYtm.sh** → entrada `👁️ Mostrar/Esconder Painel`;
- **Keybind** `SUPER + CTRL + Y` (adicionado pelo `install.sh` no
  `Keybinds.conf` — recarregue com `hyprctl reload`).

Ambos chamam `~/.local/bin/hyprwave-panel-toggle`, que alterna a visibilidade
do hyprwave e grava o estado em `/tmp/ytm_panel_hidden`.

Enquanto `/tmp/ytm_panel_hidden` existir, o `open_panel` do launcher **não**
reabre o painel automaticamente ao tocar uma música: ele sobe o hyprwave
(se preciso) e a bridge, mas respeita o seu estado manual. Para o painel voltar
a aparecer sozinho, basta usar o toggle de novo (o flag é removido).

Nota: a notificação "Now Playing" do hyprwave continua aparecendo normalmente,
independente de o painel estar oculto.

## Troubleshooting

| Sintoma | Causa / correção |
|---|---|
| Painel não abre ao tocar | hyprwave não instalado (`command -v hyprwave`) → `install.sh --hyprwave` |
| Painel mostra "Youtube Music" em vez do nome | título chegou vazio à bridge — no launcher, `choice` é capturado por `pick_from_helper` via `$(...)` (subshell) e `play_url` aplica o título via `mpvctl title`; conferir que a bridge semeia o `media-title`. A bridge resolve o nome real mesmo assim (via `yt-dlp`/flat-playlist) |
| Painel mostra o título do mpv nativo, não o da bridge | hyprwave conectou no MPRIS nativo do mpv antes de a bridge nascer → precisa do patch `hyprwave-reconnect.patch` aplicado no build (reinstalar com `install.sh --hyprwave`); validar: `grep -E "preferred player" ~/.config/.../hyprwave.log` mostra `ytm` e não `mpv` |
| Painel sem thumbnail | a bridge não resolveu a art: testar na mão `yt-dlp -J "https://music.youtube.com/watch?v=<id>"` com o venv (deve listar `thumbnails`) e conferir se a bridge está viva (`pgrep -f ytm/mpris_bridge`) |
| Botões próxima/anterior desabilitados | faixa única (sem playlist) = correto; se **em playlist**: conferir que tocou a URL `.../playlist?list=...` (não a watch), `mpvctl playlist` deve mostrar `count > 1`, e `playerctl -p ytm metadata` deve ter `xesam:title` mudando no next |
| Hyprwave pegando o player errado | `preference` deve ter `ytm` antes de `mpv`; patch de reconnect aplicado no build (senão ele fica preso no player que nasceu primeiro) |
| Sem ondas no painel | visualizer usa PulseAudio: conferir `pactl info` e se o PipeWire-pulse está ativo; `[Visualizer] enabled=true` no config |
| Painel congela/volta ao idle no fim da música | mpv morreu (fim da faixa) → bridge sai → painel volta ao visualizer idle (comportamento por design) |
| `hyprwave-toggle` diz "not running" | painel fechado por completo → `RofiYtm.sh` reabre ao tocar música |
| Ondas pulam/trepitam durante a reprodução | build do hyprwave sem `hyprwave-jitter.patch` → reinstalar com `install.sh --hyprwave` |
| Ondas CONGELAM (paradas) com a música tocando | versão antiga do build recarregava a capa do álbum (download HTTP síncrono) e o ícone de play/pause a cada `PropertiesChanged` do MPRIS (~2x/s), travando o main loop do GTK e o render das barras de 60fps → a partir de agora só reconstrói a capa na troca de música e o ícone na troca de estado; se o binário for antigo, reinstalar com `install.sh --hyprwave` |
| Painel não reabre ao tocar música depois de eu escondê-lo | comportamento por design: `/tmp/ytm_panel_hidden` existe (você escondeu manualmente) → use o toggle (`👁️ Mostrar/Esconder Painel` ou `SUPER+CTRL+Y`) para voltar ao auto-mostrar |