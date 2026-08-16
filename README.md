# rofi-ytm

**YouTube Music (da sua conta) dentro do rofi.**

Pesquise músicas no catálogo do YouTube Music, acesse suas curtidas e playlists,
escolha a faixa com o rofi e toque no `mpv` — tudo de forma mínima, sem abrir
navegador.

```text
rofi -> sua conta YouTube Music (ytmusicapi) -> listas -> mpv + yt-dlp
```

## Funcionalidades

- 🔎 **Search YouTube Music** — busca no catálogo completo (filtro `songs`, 20 resultados)
- ❤️ **Liked Songs** — suas músicas curtidas (até 100)
- 📁 **My Playlists** — todas as playlists da biblioteca, com submenu
  - ▶️ **Play whole playlist** — toca a playlist inteira pelo ID
  - 🎵 **Pick a song** — lista as faixas (até 200) e você escolhe
- Notificação na tela com a faixa atual (`swaync` + ícone `music.png`)
- **Painel "Now Playing"** (Hyprwave): nome real da música, thumbnail do YouTube,
  progresso/volume e controles play/pause/próxima/anterior — em faixa única e
  em playlists inteiras (via bridge MPRIS `org.mpris.MediaPlayer2.ytm`)
- 🎤 **Painel de letras** (karaokê ANSI em uma janela kitty): letras sincronizadas
  do lrclib.net (fallback letra completa/instrumental), layout que se ajusta ao
  tamanho do terminal com quebra só por palavra inteira — abre junto com a
  música, fecha no stop (`SUPER CTRL L` ou menu → 🎤 Letras)
- Encerra a música atual antes de tocar a próxima (mantém `mpvpaper` vivo)
- Autenticação **automática** com sua conta: os headers são regenerados a partir
  do Firefox sempre que o cookie expira — sem passo manual (com 2+ contas, um
  seletor escolhe qual usar)

## Atalhos

| Atalho | Ação |
|---|---|
| `SUPER SHIFT Y` | Abre o menu YouTube Music diretamente |
| `SUPER SHIFT M` | Menu Online Music (RofiBeats) → opção "Play from YouTube Music 🎧" |
| `SUPER CTRL Y` | Mostra/esconde o painel do Hyprwave (adicionado pelo instalador) |
| `SUPER CTRL L` | Abre/fecha o painel de letras (adicionado pelo instalador) |

## Instalação rápida

Pré-requisitos: `rofi`, `mpv`, `notify-send` (libnotify), Firefox (com login no
YouTube) e um Python 3.10+.

**Forma recomendada — instalador reproduzível:**

```bash
./install.sh                 # instala deps do sistema (sudo), venv, deno,
                             # provider, detecta o perfil Firefox e deploya
                             # tudo de src/ nos lugares certos
./install.sh --help          # todas as opções (--no-deps, --prefix, --uninstall...)
```

> **Painel "Now Playing":** para ativá-lo também, rode `./install.sh --hyprwave`
> (builda e instala o Hyprwave + adiciona o keybind `SUPER CTRL Y`).
> Sem ele a música toca normal — só o painel não abre.

O instalador cobre Ubuntu/Debian (apt), Arch (pacman) e Fedora (dnf), detecta
o perfil do Firefox (snap → nativo → flatpak), aplica fallbacks quando os temas
KoolDots/ícones não existirem, roda a verificação final (API + PO token com
`pot=`) e **apenas imprime** as instruções do keybind — não altera suas configs.

Forma manual (equivalente ao que o instalador faz):

```bash
# 1. venv com as libs
python3 -m venv ~/.local/share/ytm-venv
~/.local/share/ytm-venv/bin/pip install ytmusicapi browser-cookie3 yt-dlp bgutil-ytdlp-pot-provider dbus-next

# 2. deno (runtime JS do yt-dlp para o desafio de assinaturas)
curl -fsSL https://deno.land/install.sh | sh -s -- -y

# 3. provider binário do PO Token (bgutil) + deps node
git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
(cd ~/bgutil-ytdlp-pot-provider/server && npm ci --frozen-lockfile)

# 4. copiar os scripts de src/ para os destinos de "Onde vive o sistema real"
#    (src/ytm.py, src/refresh_auth.py, src/RofiYtm.sh, src/mpvctl.py,
#     src/mpris_bridge.py, src/hyprwave-panel-toggle.sh,
#     src/lyrics_player.py, src/lyrics-panel-toggle.sh — chmod +x)

# 5. (opcional) painel "Now Playing": buildar/instalar o Hyprwave
#    sudo apt install libgtk4-layer-shell-dev
#    git clone https://github.com/shantanubaddar/hyprwave /tmp/hyprwave
#    cd /tmp/hyprwave && for p in /path/to/rofi-ytm/src/hyprwave/*.patch; do git apply "$p"; done
#    make && PREFIX=~/.local make install
#    mkdir -p ~/.config/hyprwave && cp /path/to/rofi-ytm/src/hyprwave/config.conf ~/.config/hyprwave/
```

> Detalhes completos, o passo a passo de instalação e a configuração de teclas
> estão em [`docs/02-architecture.md`](docs/02-architecture.md).

## Estrutura

```text
rofi-ytm/
├── README.md
├── install.sh                # instalador reproduzível (deps, venv, deploy)
├── src/                      # scripts-fonte (fonte da verdade dos deployados)
│   ├── RofiYtm.sh            # interface rofi (placeholders resolvidos no deploy)
│   ├── ytm.py                # helper da API
│   ├── refresh_auth.py       # regenerador de credencial
│   ├── mpvctl.py             # cliente do socket JSON do mpv (p/ o painel)
│   ├── mpris_bridge.py       # player MPRIS com título real + thumbnail + next/prev
│   ├── hyprwave-panel-toggle.sh  # mostra/esconde o painel (menu + keybind)
│   ├── lyrics_player.py      # karaokê ANSI das letras (lrclib + MPRIS)
│   ├── lyrics-panel-toggle.sh   # abre/fecha/redimensiona a janela de letras
│   └── hyprwave/             # config do Hyprwave + patches aplicados no build
└── docs/
    ├── 01-overview.md          # visão geral, stack e fluxo
    ├── 02-architecture.md      # componentes e instalação em detalhe
    ├── 03-authentication.md    # autenticação (headers do navegador + SAPISIDHASH)
    ├── 04-playback.md          # playback (PO Token, deno, yt-dlp, mpv)
    ├── 05-troubleshooting.md   # problemas comuns e correções
    ├── 06-history.md           # jornada completa e decisões de projeto
    ├── 07-now-playing-panel.md # painel "Now Playing" (Hyprwave + bridge MPRIS)
    └── 08-lyrics-panel.md      # painel de letras (karaokê ANSI em janela kitty)
```

## Onde vive o sistema real

| Caminho | Papel |
|---|---|
| `~/.config/hypr/UserScripts/RofiYtm.sh` | Interface rofi (script principal) |
| `~/.config/rofi/scripts/ytm/ytm.py` | Helper: busca/curtidas/playlists via ytmusicapi |
| `~/.config/rofi/scripts/ytm/refresh_auth.py` | Regenera headers_auth.json a partir do Firefox |
| `~/.config/rofi/scripts/ytm/mpvctl.py` | Cliente do socket JSON do mpv (`ping`, `next`, `prev`...) |
| `~/.config/rofi/scripts/ytm/mpris_bridge.py` | Player MPRIS `org.mpris.MediaPlayer2.ytm` (painel) |
| `~/.config/rofi/scripts/ytm/lyrics_player.py` | Karaokê ANSI das letras (lê a bridge via D-Bus + lrclib.net) |
| `~/.config/rofi/scripts/ytm/headers_auth.json` | Headers autenticados (**chmod 600, nunca commitar**) |
| `~/.local/share/ytm-venv/` | venv Python (ytmusicapi, browser-cookie3, yt-dlp, plugin, dbus-next) |
| `~/bgutil-ytdlp-pot-provider/` | Provider de PO Token (clone + `server/node_modules`) |
| `~/.deno/` | Runtime JS do yt-dlp |
| `~/.local/bin/hyprwave` | Painel "Now Playing" (instalado com `install.sh --hyprwave`) |
| `~/.local/bin/hyprwave-panel-toggle` | Mostra/esconde o painel (menu + `SUPER CTRL Y`) |
| `~/.local/bin/lyrics-panel-toggle` | Abre/fecha/redimensiona o painel de letras (menu + `SUPER CTRL L`) |
| `/tmp/ytm_songs.{tsv,lines}` | Artefatos temporários de cada listagem |

> Os caminhos acima são os **deployados** pelo `install.sh` a partir de `src/`
> (perfil do Firefox, venv e diretórios são detectados e substituídos no deploy).

## Segurança

- `headers_auth.json` contém **cookies reais de sessão** — ele fica `chmod 600`
  e **não** deve ser versionado nem compartilhado. Se vazar, revogue a sessão
  pelo navegador.
- Este repositório documenta o sistema; nenhum segredo foi commitado.