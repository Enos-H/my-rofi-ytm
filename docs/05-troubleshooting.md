# 05 — Troubleshooting

Sintoma → causa → correção, organizado por área. Ordene pelos itens marcados
[frequente]. Referências: autenticação [`03-authentication.md`](03-authentication.md),
playback [`04-playback.md`](04-playback.md), painel [`07-now-playing-panel.md`](07-now-playing-panel.md),
letras [`08-lyrics-panel.md`](08-lyrics-panel.md).

## Autenticação / API

| Sintoma | Causa provável | Correção |
|---|---|---|
| Notificação "Nenhum cookie do YouTube encontrado no Firefox..." | Nenhum cookie de youtube.com no perfil (ou perfil errado) | Checar `YTM_PROFILE`; abrir youtube.com logado; rodar `refresh_auth.py` |
| "Sessão do YouTube não encontrada no Firefox..." | Firefox deslogado do YouTube | Fazer login em youtube.com e tentar de novo (a recuperação é automática) |
| "Falha ao acessar a página do YouTube Music..." | Sem conexão / HTML mudou | Verificar rede; conferir se a página ainda expõe `DATASYNC_ID` |
| "No auth found. Run refresh_auth.py first" [frequente após limpeza] | `headers_auth.json` inexistente | Rodar `~/.config/rofi/scripts/ytm/refresh_auth.py` uma vez (com o python do **venv**) |
| Busca funciona, mas a notificação diz "Auth error - check Firefox login" | stderr do helper propagado | Ver o stderr direto: `ytm.py search "x"` no terminal |
| Campo da busca retorna vazio/silencioso (exit 0 sem saída) | Guard `if __name__ == "__main__": main()` removido do ytm.py | Restaurar o guard no fim do arquivo (lição de 06-history) |
| Liked/playlists dizem "Sign in to listen to your liked tracks" | `x-goog-authuser` apontando para sessão inexistente | Rodar `refresh_auth.py` (ou menu **🔄 Recarregar Cookies**) — o authuser é **autodetectado** (0..4) |
| Músicas da conta errada com 2+ contas logadas | Cookies valem para todas as contas; o header `x-goog-authuser` define qual; autodetecção pega a 1ª válida | Menu **🔄 Recarregar Cookies**: com 2+ contas abre seletor (**•** = preferida, `account_pref`); volta sozinho para a 1ª válida se a preferida sumir |
| `refresh_auth.py` manual falha com "No module named 'browser_cookie3'" | Rodado com o python do sistema | Usar o python do venv (`~/.local/share/ytm-venv/bin/python`) |

## Playback (mpv / yt-dlp)

| Sintoma | Causa provável | Correção |
|---|---|---|
| mpv abre e fica 0% CPU, sem áudio ("HTTP error 403 Forbidden") [frequente] | URL nasce sem `pot=` (PO Token) | Conferir as 3 `--ytdl-raw-options` do `play_url()`; plugin e deno OK (abaixo) |
| `yt-dlp -v` sem "PO Token Providers" | Plugin bgutil não carregado | Rodar yt-dlp do **venv** (`~/.local/share/ytm-venv/bin/yt-dlp -v`) — plugins pip não valem para yt-dlp global |
| "No supported JavaScript runtime could be found" | deno ausente ou fora do PATH | `curl -fsSL https://deno.land/install.sh \| sh -s -- -y`; `$HOME/.deno/bin` no PATH do `play_url()` |
| "web_music client https formats require a GVS PO Token... skipped" | sem cookies OU provider não ativo | `--cookies-from-browser` com o perfil snap; plugin verificado |
| "Signature solving failed... only images" | sem `remote-components=ejs:github` | Adicionar a flag ao `play_url()` |
| `python -m yt_dlp` ou yt-dlp global funciona, mpv não | mpv pegou o yt-dlp errado no PATH | PATH do mpv com venv **primeiro**: `env PATH=venv:deno:$PATH` |
| Música toca, mas "only images" no `-F` | Cliente `web` (default) | Usar `player_client=web_music` |
| Erro ao tocar playlist privada | mpv sem cookies da conta | `cookies-from-browser=firefox:<perfil>` em `play_url()` |
| `Database is locked` (Firefox) | yt-dlp lendo cookies.sqlite com o Firefox aberto | Em geral o snap profile funciona com o Firefox aberto; se ocorrer: fechar o Firefox, ou exportar `cookies.txt` e usar `--cookies <arquivo>` |
| mpv morre no meio da música (stall do stream `web_music`) | comportamento conhecido do ambiente | A música para e a bridge/letras saem (design); tocar de novo. O hyprwave fica no idle |

## Painel "Now Playing" (Hyprwave)

| Sintoma | Causa provável | Correção |
|---|---|---|
| Painel não abre ao tocar | hyprwave não instalado | `command -v hyprwave` → `install.sh --hyprwave` |
| Painel mostra "Youtube Music" em vez do nome | título do mpv veio vazio (choice via subshell) | `play_url <url> "$song_title"` (2º arg); a bridge resolve o nome real via yt-dlp mesmo assim |
| Painel mostra título do mpv nativo, não o da bridge | hyprwave conectou no MPRIS nativo antes da bridge nascer | Precisa do `hyprwave-reconnect.patch` no build (reinstalar `install.sh --hyprwave`); validar no log: `grep -E "preferred player"` mostra `ytm` |
| Painel sem thumbnail | bridge não resolveu a art | Testar `yt-dlp -J "<watch url>"` no venv; bridge viva? (`pgrep -f ytm/mpris_bridge`) |
| Botões próxima/anterior desabilitados | faixa única = correto; **em playlist**: URL deve ser `playlist?list=...` | `mpvctl playlist` → `count > 1`; `playerctl -p ytm metadata` muda no next |
| Hyprwave pegando o player errado | `preference` sem `ytm` primeiro / sem patch de reconnect | config.conf + reinstalar |
| Sem ondas no painel | visualizer usa PulseAudio | `pactl info`; PipeWire-pulse ativo; `[Visualizer] enabled=true` |
| Ondas pulam/trepitam durante a reprodução | build sem `hyprwave-jitter.patch` | Reinstalar com `install.sh --hyprwave` |
| Ondas CONGELAM (paradas) com a música tocando | build antigo recarregava capa (HTTP síncrono) + ícone a cada `PropertiesChanged` (~2x/s), travando o main loop GTK | Reinstalar `install.sh --hyprwave` (fix no `hyprwave-reconnect.patch`) |
| Painel congela/volta ao idle no fim da música | mpv morreu (fim da faixa) → bridge sai | Comportamento por design |
| `hyprwave-toggle` diz "not running" | painel fechado por completo | `RofiYtm.sh` reabre ao tocar música |
| Painel não reabre ao tocar depois de eu escondê-lo | `/tmp/ytm_panel_hidden` existe (estado manual) | Usar o toggle (`👁️` ou `SUPER+CTRL+Y`) para voltar ao auto-mostrar |

## Painel de letras (karaokê ANSI)

| Sintoma | Causa provável | Correção |
|---|---|---|
| Janela de letras não abre ao tocar | toggle/player ausente ou morto | `command -v lyrics-panel-toggle`; `pgrep -f ytm/lyrics_player`; abrir na mão `lyrics-panel-toggle open` |
| A letra não aparece / "Letra não encontrada" | música sem registro no lrclib, ou D-Bus sem bridge | Testar a busca na mão com o venv; `pgrep -f ytm/mpris_bridge` |
| A letra não acompanha a música | sem LRC sincronizado no lrclib → fallback plain (aproximado) | Para sincronia perfeita a faixa precisa de `syncedLyrics` |
| Palavra quebrada no meio (ex. "ba" / "by") | layout antigo (60 colunas fixas) | Reinstalar `lyrics_player.py` (o atual se ajusta ao terminal) |
| Janela fica no caminho / gigante | tamanho padrão pequeno demais? | Submenu `📐` (Compacta 420×300 / Média 600×400 / Grande 800×600) |
| Janela some ao trocar de workspace | build antigo sem `pin` na windowrule | Reinstalar/atualizar WindowRules.conf (`pin = on`, `no_focus = on`) |
| Keybind `SUPER+CTRL+L` não funciona | Hyprland não recarregado | `hyprctl reload`; conferir linha `Toggle YTM lyrics` no Keybinds.conf |

## Depuração (comandos)

```bash
# 1. Log do mpv com verbosidade (sem --no-terminal)
mpv --msg-level=all=status --no-video \
  --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
  --ytdl-raw-options="remote-components=ejs:github" \
  --ytdl-raw-options="cookies-from-browser=firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
  'https://music.youtube.com/watch?v=<videoId>'

# 2. Provider de PO token
~/.local/share/ytm-venv/bin/yt-dlp -v 2>&1 | grep -i "PO Token"

# 3. Extração manual (URL da faixa + pot)
~/.local/share/ytm-venv/bin/yt-dlp -f bestaudio/best -g \
  --extractor-args "youtube:player_client=web_music" \
  --remote-components ejs:github \
  --cookies-from-browser "firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
  'https://music.youtube.com/watch?v=<videoId>'
#  -> URL válida contém "pot="; se não tiver, o provider não está ativo

# 4. Auth manual (sempre com o python do venv)
~/.local/share/ytm-venv/bin/python ~/.config/rofi/scripts/ytm/refresh_auth.py

# 5. Estado do painel (layers)
hyprctl layers -j | grep -F '"namespace": "hyprwave"'

# 6. MPRIS da bridge
playerctl -p ytm metadata

# 7. UI completa
~/.config/hypr/UserScripts/RofiYtm.sh
```

## Checklist rápido (música não toca)

1. `ytm.py search "teste"` → retorna lista? (senão: auth, seção Auth/API)
2. `yt-dlp -v | grep "PO Token"` → provider presente? (senão: venv/plugin/deno)
3. Extração manual contém `pot=`? (senão: flags do mpv)
4. Teste de URL: `curl -sI "<url do passo 3>"` → 200? (senão: atualizar yt-dlp)
