# 08 — Painel de letras (karaokê ANSI)

Enquanto uma música toca, um **terminal dedicado** (janela `kitty`
flutuante) mostra a **letra da música** sincronizada com a reprodução,
no estilo de um karaokê de terminal (letra ativa em destaque, demais
em cinza). O projeto de referência (código-base para a animação ANSI)
é `sabymarqy-ship-it/C-DIGO-BASE-PARA-A-LYRICS`.

```
RofiYtm.sh ──▶ mpris_bridge.py (org.mpris.MediaPlayer2.ytm)   ──▶ hyprwave
                        │
                        │  D-Bus MPRIS (título, artista, duração,
                        │  posição ao vivo, trackid)
                        ▼
              lyrics_player.py (venv, dbus-next)
                        │  letra via lrclib.net (LRC sincronizado;
                        │  fallback: letra completa distribuída pela
                        │  duração; "Letra não encontrada")
                        ▼
              kitty --class ytm-lyrics "--title Letras" (terminal float)
```

## Como funciona

- O `lyrics_player.py` consulta o player MPRIS da bridge
  (`org.mpris.MediaPlayer2.ytm`, com fallback para o MPRIS nativo do
  mpv), por um poll de 0.2s: `xesam:title`, `xesam:artist`,
  `mpris:length` (duração em µs), `Position` (posição em µs) e
  `PlaybackStatus`.
- A letra é buscada no **lrclib.net** a partir do título/artista:
  1. `GET /api/get?artist_name=...&track_name=...`;
  2. se falhar, busca progressiva em `/api/search?q=...` (primeiro
     "título artista", depois só título), pegando a primeira entrada
     com `syncedLyrics`;
  3. com LRC sincronizado (`[mm:ss.xx]`), renderiza a linha ativa de
     acordo com a posição real do mpv; com só letra em texto, distribui
     as linhas ao longo da duração; `instrumental` mostra aviso;
  4. sem resultado, mostra "Letra não encontrada".
- O resultado é cacheado por tupla `trackid|título|artista` (`/ytm/<id>`
  do YouTube) em memória **e em disco** (`~/.cache/rofi-ytm/lyrics.json`,
  TTL 7 dias) — a busca é feita uma vez por faixa, mesmo entre sessões.
  Chavear por metadata (e não só pelo `trackid`) evita reusar a letra da
  faixa anterior quando a metadata muda na transição entre faixas da fila/
  playlist;
- **Transição entre faixas**: ao trocar de música (fila/playlist) o mpv fica
  brevemente sem `filename` e a bridge reportaria `Stopped` — o player só
  fecha após ~3s contínuos de `Stopped` (`STOPPED_LIMIT`), então a janela
  de letras **não fecha no meio de uma playlist**.
- O layout se **adapta ao tamanho do terminal**: a largura/textura de
  renderização é recalculada do tamanho real da janela (e re-renderizada
  se ela for redimensionada), então o texto nunca é cortado pelo
  terminal no meio de uma palavra — a quebra é sempre por palavra
  inteira.
- **Espaçamento inteligente entre versos**: as linhas de um mesmo verso
  (que por ventura quebrem em mais de uma linha de terminal) ficam
  consecutivas, e entre dois versos diferentes entra **exatamente uma
  linha vazia** — não depende de um valor fixo de linhas em branco.
- A janela **abre junto** com a música (o launcher chama
  `lyrics-panel-toggle open` no `play_url`/`Now Playing`) e **fecha
  junto** no `stop_music`. O player também **sai sozinho** quando o
  mpv para (posição/música some por ~4s — incluindo o daemon ocioso no
  fim da fila sem loop).

## Componentes (deploy)

| Arquivo | Função |
|---|---|
| `$CONFIG_DIR/rofi/scripts/ytm/lyrics_player.py` | player de letras (venv + dbus-next): lê o MPRIS da bridge, busca no lrclib e renderiza o karaokê ANSI |
| `~/.local/bin/lyrics-panel-toggle` (de `src/lyrics-panel-toggle.sh`) | controla a janela do kitty: abre (`open`), fecha (`close`), alterna (`visibility`), redimensiona (`size compacta/media/grande`); pidfile `/tmp/ytm_lyrics.pid` |

Dependência Python: `dbus-next` (já instalado no venv pelo `install.sh`
para a bridge MPRIS).

## Abrir/fechar — keybind e menu

- **Keybind** `SUPER + CTRL + L` (adicionado pelo `install.sh` no
  `Keybinds.conf` — recarregue com `hyprctl reload`):
  `~/.local/bin/lyrics-panel-toggle visibility`.
- **Menu RofiYtm.sh** → entrada `🎤 Letras` abre um submenu:
  - `🎤 Mostrar/Esconder Letras` → alterna a janela;
  - `📐 Compacta` / `📐 Média` / `📐 Grande` → redimensiona a janela
    (420×300 / 600×400 / 800×600), via
    `hyprctl dispatch resizewindowpixel exact <W> <H>,address:<win>`.
- O `install.sh` também insere as windowrules do Hyprland no
  `WindowRules.conf` (idempotente): a janela `class^(ytm-lyrics)$` é
  **flutuante**, posicionada à direita do painel do hyprwave
  (`move 1155 42`) com `size 420 300` (mantém a borda padrão), **fixada
  em todos os workspaces** (`pin = on` — acompanha o painel, que é uma
  layer surface) e **nunca rouba o foco** (`no_initial_focus` +
  `no_focus` — display-only).

## Troubleshooting

| Sintoma | Causa / correção |
|---|---|
| Janela de letras não abre ao tocar | conferir `command -v lyrics-panel-toggle` e se o player está vivo (`pgrep -f ytm/lyrics_player`); abrir na mão `lyrics-panel-toggle open` |
| A letra não aparece / "Letra não encontrada" | música sem registro no lrclib (o tocar da letra vem do próprio player) — ou o D-Bus está sem a bridge (`pgrep -f ytm/mpris_bridge`) e o mpv nativo também não responde; testar a busca na mão com o venv |
| A letra não acompanha a música | sem LRC sincronizado no lrclib → fallback `plain` distribui as linhas pela duração (aproximado); para sincronia perfeita a faixa precisa de `syncedLyrics` |
| Palavra quebrada no meio (ex. "ba" / "by") | layout antigo fixo em 60 colunas; reinstale o `lyrics_player.py` (o atual se ajusta ao tamanho do terminal e quebra só por palavra inteira) |
| Janela fica no caminho / gigante | usar o submenu `📐` para redimensionar, ou mover/redimensionar na mão (a janela é float); o tamanho padrão é 420×300 à direita do painel |
| Keybind `SUPER+CTRL+L` não funciona | recarregar o Hyprland (`hyprctl reload`) após o `install.sh`; conferir que a linha `Toggle YTM lyrics` está no `Keybinds.conf` |