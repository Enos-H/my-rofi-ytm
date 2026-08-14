# 02 — Arquitetura dos componentes

Este documento detalha cada componente do sistema, seu contrato e como se
ligam. Os scripts de referência vivem fora deste repositório; este doc os
espelha com fidelidade.

---

## 1. `RofiYtm.sh` — interface rofi (Bash)

**Local:** `~/.config/hypr/UserScripts/RofiYtm.sh` (executável)

### Variáveis globais

| Variável | Valor | Uso |
|---|---|---|
| `iDIR` | `$XDG_CONFIG_HOME/.config/swaync/icons` | ícone das notificações (`music.png`) |
| `rofi_theme` | `config-rofi-Beats.rasi` | tema da lista de músicas |
| `rofi_theme_menu` | `config-rofi-Beats-menu.rasi` | tema dos menus |
| `PYTHON` | `~/.local/share/ytm-venv/bin/python` | Python do venv |
| `HELPER` | `~/.config/rofi/scripts/ytm/ytm.py` | helper da API |
| `TSV_FILE` | `/tmp/ytm_songs.tsv` | linha ↦ id |
| `LINES_FILE` | `/tmp/ytm_songs.lines` | linhas exibíveis |

> `choice` e `line_num` são globais de propósito: `play_url()` usa
> `${choice:-YouTube Music}` como título da notificação.

### Funções

**`notification()`** — `notify-send -u normal -i "$iDIR/music.png" "$@"`.
Compacta o envio com tema do swaync.

**`stop_music()`** — encerra a reprodução anterior preservando o `mpvpaper`:

```bash
mpv_pids=$(pgrep -x mpv)                       # só mpv, nunca o shell
mpvpaper_pid=$(ps aux | grep -- 'unique-wallpaper-process' | grep -v grep | awk '{print $2}')
for pid in $mpv_pids; do
  ! echo "$mpvpaper_pid" | grep -q "$pid" && kill -9 $pid || true
done
```

- Usa `pgrep -x mpv` (match exato do nome do processo). **Nunca** `pkill -f` com
  padrão que apareça na linha de comando do próprio shell (lição 06-history).
- `unique-wallpaper-process` é a marca do processo do mpvpaper; se o pid do mpv
  estiver nela, é wallpaper — não mata.

**`play_url()`** — para a música atual, notifica e sobe o mpv isolado:

```bash
setsid env PATH="$HOME/.local/share/ytm-venv/bin:$HOME/.deno/bin:$PATH" \
  mpv --no-video --no-terminal --ytdl-format=bestaudio/best \
    --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
    --ytdl-raw-options="remote-components=ejs:github" \
    --ytdl-raw-options="cookies-from-browser=firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
    "$1" >/dev/null 2>&1 &
```

Cada flag é crítica (detalhadas em [`04-playback.md`](04-playback.md)):

| Flag | Motivo |
|---|---|
| `setsid env PATH=venv:deno` | mpv 0.41 **não tem** `--ytdl-exec`; o yt-dlp é resolvido pelo PATH — venv primeiro (2026.07.04), deno depois |
| `--no-video` | modo áudio |
| `--no-terminal` | silencioso (também suprime logs — ver troubleshooting) |
| `--ytdl-format=bestaudio/best` | melhor áudio disponível |
| `extractor-args=...player_client=web_music` | cliente que expõe formatos de áudio de verdade |
| `remote-components=ejs:github` | baixa o solver JS de assinaturas |
| `cookies-from-browser=firefox:<perfil>` | perfil **snap** do Firefox — login da conta |

**`pick_from_helper()`** — o coração da ponte Python ↔ rofi:

```bash
if ! err=$("$PYTHON" "$HELPER" "$@" 2>&1 >/dev/null); then
  notify-send -u critical -i "$iDIR/music.png" "YouTube Music" "${err:-Auth error - check Firefox login}"
  exit 1
fi
choice=$(rofi -i -dmenu -config "$rofi_theme" \
  -theme-str 'entry { placeholder: "🎵 Pick a song"; }' <"$LINES_FILE")
line_num=$(grep -nFx "$choice" "$LINES_FILE" | head -1 | cut -d: -f1)
sed -n "${line_num}p" "$TSV_FILE" | awk -F'\t' '{print $2}'   # imprime o id na stdout
```

- `2>&1 >/dev/null` captura **só o stderr** do helper; stderr ou erro → notificação
  crítica e exit 1.
- `grep -nFx` acasalado com o rofi: `-F` (literal, sem regex) e `-x` (linha
  inteira) garantem que o texto exibido ache a linha certa mesmo com acentos/emoji.
- O ID sai do TSV pela posição da linha.

**`search_music()`** — pede a query (`rofi -dmenu -lines 0` — busca livre sem
lista), delega ao `pick_from_helper search "$query"` e toca `watch?v=<id>`.

**`liked_music()`** — `pick_from_helper liked` → toca.

**`playlists_music()`** — `pick_from_helper`-like para playlists (sem rota de
erro duplicada), depois submenu:

```text
▶️  Play whole playlist     -> play_url(".../playlist?list=<id>")
🎵  Pick a song             -> pick_from_helper playlist <id> -> watch?v=<id>
```

**Menu principal** — as 3 opções com emoji (`🔎`, `❤️`, `📁`) via
`rofi -dmenu -config "$rofi_theme_menu"` com placeholder `🎧 YouTube Music`;
`case` exato decide a função.

### Contrato de saída do helper (para o Bash)

1. Sucesso: stdout com uma linha por item; escreve `TSV_FILE` e `LINES_FILE`.
2. Erro: stderr com mensagem (pt-BR) + JSON `{"message": ..., "prompt": "error"}`
   no stdout e exit 1.

---

## 2. `ytm.py` — helper da API

**Local:** `~/.config/rofi/scripts/ytm/ytm.py` (executável, shebang python3)

### Comandos

| Comando | Chamada ytmusicapi | Limite | Filtro |
|---|---|---|---|
| `search <query>` | `yt.search(q, filter="songs")` | 20 (`RESULT_COUNT`) | só músicas |
| `liked` | `yt.get_liked_songs()` | 100 | faixas com `videoId` |
| `playlists` | `yt.get_library_playlists()` | ilimitado | todas |
| `playlist <id>` | `yt.get_playlist(pid)` | 200 | faixas com `videoId` |

### Estrutura

- `fail(msg)` — mensagem **no stderr** **e** JSON `{"message","prompt":"error"}`
  no stdout, exit 1. O stderr é o que o Bash notifica; o JSON é compatível com
  layouts de erro de helpers (estilo `rofi-blocks`).
- `get_client()` — `YTM_HEADERS` (env) ou `headers_auth.json`; se ausente,
  `fail("No auth found. Run refresh_auth.py first")`.
- `refresh_auth()` — roda `refresh_auth.py` via subprocess (Python = `YTM_PYTHON`
  ou o do próprio venv), timeout 60s; se o returncode ≠ 0, propaga o stderr.
- `main()` — **auto-recuperação**: tenta o comando; em qualquer exceção, roda
  `refresh_auth()`, **reconstrói o cliente** e tenta **uma** segunda vez;
  se falhar de novo, `fail("auth error: {e}")`.
- `emit(tracks, ids)` — grava o TSV (`i\tid`) e o LINES, e imprime as linhas
  `Título - Artista(s) (duração)`; duração de `duration` (string mm:ss) ou
  `duration_seconds` (mm:ss calculado); artistas com `", ".join`.

> Armadilha conhecida: a edição desta refatoração apagou o guard
> `if __name__ == "__main__": main()` e o script passou a sair silencioso
> (exit 0, sem saída). **Sempre verifique o guard ao editar ytm.py.**

### Env vars suportadas

| Variável | Efeito |
|---|---|
| `YTM_HEADERS` | override do caminho do headers_auth.json |
| `YTM_PYTHON` | Python usado para o refresh_auth.py |
| `YTM_PROFILE` | override do perfil do Firefox (também em refresh_auth.py) |

---

## 3. `refresh_auth.py` — regenerador de credencial

**Local:** `~/.config/rofi/scripts/ytm/refresh_auth.py` — fluxo em
[`03-authentication.md`](03-authentication.md). Resumo:

1. Lê cookies do Firefox (perfil snap) com `browser-cookie3` (domínios
   `youtube.com`, `youtubei.googleapis.com`, `googlevideo.com`).
2. Descarta cookies de rastreio (`ST-`, `itct`, `csn`, `PREF`, `wide`, `_ga`,
   `_gcl_au`) e valores > 2000 chars (cookie final ≈ 2500 chars).
3. Busca `DATASYNC_ID` na página do YouTube Music (logada).
4. Gera o `SAPISIDHASH`/`SAPISID1PHASH`/`SAPISID3PHASH`.
5. Escreve `headers_auth.json` via arquivo temporário + `chmod 600` +
   `os.replace` (atômico).
6. Erros em pt-BR, no stderr, exit 1.

---

## 4. Integração com o ambiente (Hyprland + RofiBeats)

### RofiBeats (`~/.config/hypr/UserScripts/RofiBeats.sh`)

Item **"Play from YouTube Music 🎧"** adicionado ao menu (após "Play from
Music directory"):

```bash
"Play from YouTube Music 🎧") "$HOME/.config/hypr/UserScripts/RofiYtm.sh" ;;
```

### Keybinds — registrados em DOIS arquivos (sincronizados)

`~/.config/hypr/configs/system_keybinds.lua` (após `SUPER SHIFT M`):

```lua
bind("SUPER SHIFT", "Y", exec_cmd("$HOME/.config/hypr/UserScripts/RofiYtm.sh"), { description = "youtube music" })
```

`~/.config/hypr/configs/Keybinds.conf` (seção FEATURES/EXTRAS, após o RofiBeats):

```conf
bindd = $mainMod SHIFT, Y, YouTube Music, exec, $UserScripts/RofiYtm.sh
```

Após editar, recarregar: `hyprctl reload`; conferir com
`hyprctl binds -j | grep -i ytm`. Resultado esperado:

```text
key Y, modmask 65 (SUPER+SHIFT), dispatcher exec,
arg /home/enosh/.config/hypr/UserScripts/RofiYtm.sh, description 'YouTube Music'
```

---

## 5. Instalação completa (passo a passo)

```bash
# venv + deps
python3 -m venv ~/.local/share/ytm-venv
~/.local/share/ytm-venv/bin/pip install ytmusicapi browser-cookie3 yt-dlp bgutil-ytdlp-pot-provider

# deno (runtime JS para assinaturas)
curl -fsSL https://deno.land/install.sh | sh -s -- -y

# provider de PO Token (clone + deps node)
git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
(cd ~/bgutil-ytdlp-pot-provider/server && npm ci --frozen-lockfile)

# scripts auxiliares
mkdir -p ~/.config/rofi/scripts/ytm
#  -> copiar src/ytm.py, src/refresh_auth.py (chmod +x) e src/RofiYtm.sh (chmod +x)
#     (src/RofiYtm.sh e src/refresh_auth.py têm placeholders __VENV_DIR__,
#      __DENO_DIR__, __CONFIG_DIR__ e __FIREFOX_PROFILE__ — troque pelos
#      caminhos reais; o install.sh faz isso automaticamente)

# primeira credencial: gerada automaticamente no primeiro uso
# (requisito: Firefox logado no youtube.com)
```

### Verificação pós-instalação

```bash
# auth + busca (esperado: 20 linhas "título - artista (duração)")
~/.local/share/ytm-venv/bin/python ~/.config/rofi/scripts/ytm/ytm.py search "pink floyd"

# plugin de PO token carregado (esperado: PO Token Providers: bgutil:script-deno-1.3.1)
~/.local/share/ytm-venv/bin/yt-dlp -v 2>&1 | grep -i "PO Token"

# playback de teste (esperado: mpv vivo com áudio)
~/.config/hypr/UserScripts/RofiYtm.sh   # prova real pela UI
```

---

## 6. Instalador (`install.sh`)

Reproduz todo o setup em outro sistema (Ubuntu/Debian, Arch, Fedora), a partir
dos fontes em `src/`.

```bash
./install.sh                              # tudo
./install.sh --help                       # opções completas
./install.sh --uninstall                  # remove o que foi instalado
```

### Opções

| Flag | Efeito |
|---|---|
| `--profile <dir>` | Perfil Firefox (pula a auto-detecção) |
| `--prefix <dir>` | venv Python (default `~/.local/share/ytm-venv`) |
| `--config-dir <dir>` | Onde deploya os scripts (default `~/.config`) |
| `--no-deps` | Não instala pacotes do sistema (nada de sudo) |
| `--skip-verify` | Pula a verificação final (API + PO token) |
| `--uninstall` | Remove venv, provider, helpers e launcher (com confirmação) |
| `-h / --help` | Ajuda |

Env vars: `YTM_PROFILE`, `YTM_VENV`, `YTM_CONFIG_DIR`, `YTM_PROVIDER_DIR`,
`DENO_INSTALL`.

### Fluxo

1. **Deps do sistema** (sudo, com confirmação): mapa de pacotes por distro
   (`apt`/`pacman`/`dnf`) para rofi, mpv, libnotify, git, curl, node, npm,
   python3 + venv — só instala o que falta.
2. **venv** em `--prefix` + `pip install ytmusicapi browser-cookie3 yt-dlp
   bgutil-ytdlp-pot-provider`.
3. **deno** (script oficial) em `DENO_INSTALL` (default `~/.deno`).
4. **Provider bgutil**: clone `Brainicism/bgutil-ytdlp-pot-provider` +
   `npm ci --frozen-lockfile` em `server/`, depois **warmup do deno**
   (`generate_once.ts --version`) — a primeira execução baixa deps do deno e
   pode estourar o timeout de 15s do plugin se deixada para o primeiro playback.
5. **Detecção do perfil Firefox**: `--profile`/`YTM_PROFILE` → perfil snap →
   `~/.mozilla/firefox/*.default*` → flatpak (mais novo por mtime); valida
   `cookies.sqlite` + `key4.db`.
6. **Deploy**: `src/ytm.py` + `src/refresh_auth.py` →
   `$CONFIG_DIR/rofi/scripts/ytm/`; `src/RofiYtm.sh` → `$CONFIG_DIR/hypr/
   UserScripts/` (se existir `$CONFIG_DIR/hypr`) **ou** `~/.local/bin/`.
   Substitui `__VENV_DIR__`, `__DENO_DIR__`, `__CONFIG_DIR__` e
   `__FIREFOX_PROFILE__`. Fallbacks: sem temas `config-rofi-Beats*.rasi` →
   remove os `-config` (tema padrão do rofi); sem ícone swaync → notificação
   sem `-i`.
7. **Bootstrap de auth**: roda `refresh_auth.py` (não-fatal — se falhar,
   imprime como rodar manualmente).
8. **Verificação** (pode pular com `--skip-verify`): busca de teste via
   `ytm.py` + extração real com as flags do `play_url` — confere que a URL
   gerada contém `pot=` (prova de que o provider bgutil está ativo).
9. **Keybind**: imprime apenas as instruções (`bindd` para `Keybinds.conf` ou
   `bind` para `hyprland.conf` + `hyprctl reload`) — **não altera nenhuma
   config** do usuário.