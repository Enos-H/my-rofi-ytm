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
- Encerra a música atual antes de tocar a próxima (mantém `mpvpaper` vivo)
- Autenticação **automática** com sua conta: os headers são regenerados a partir
  do Firefox sempre que o cookie expira — sem passo manual

## Atalhos

| Atalho | Ação |
|---|---|
| `SUPER SHIFT Y` | Abre o menu YouTube Music diretamente |
| `SUPER SHIFT M` | Menu Online Music (RofiBeats) → opção "Play from YouTube Music 🎧" |

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

O instalador cobre Ubuntu/Debian (apt), Arch (pacman) e Fedora (dnf), detecta
o perfil do Firefox (snap → nativo → flatpak), aplica fallbacks quando os temas
KoolDots/ícones não existirem, roda a verificação final (API + PO token com
`pot=`) e **apenas imprime** as instruções do keybind — não altera suas configs.

Forma manual (equivalente ao que o instalador faz):

```bash
# 1. venv com as libs
python3 -m venv ~/.local/share/ytm-venv
~/.local/share/ytm-venv/bin/pip install ytmusicapi browser-cookie3 yt-dlp bgutil-ytdlp-pot-provider

# 2. deno (runtime JS do yt-dlp para o desafio de assinaturas)
curl -fsSL https://deno.land/install.sh | sh -s -- -y

# 3. provider binário do PO Token (bgutil) + deps node
git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
(cd ~/bgutil-ytdlp-pot-provider/server && npm ci --frozen-lockfile)

# 4. copiar os scripts de src/ para os destinos de "Onde vive o sistema real"
#    (src/ytm.py, src/refresh_auth.py, src/RofiYtm.sh — chmod +x)
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
│   └── refresh_auth.py       # regenerador de credencial
└── docs/
    ├── 01-overview.md          # visão geral, stack e fluxo
    ├── 02-architecture.md      # componentes e instalação em detalhe
    ├── 03-authentication.md    # autenticação (headers do navegador + SAPISIDHASH)
    ├── 04-playback.md          # playback (PO Token, deno, yt-dlp, mpv)
    ├── 05-troubleshooting.md   # problemas comuns e correções
    └── 06-history.md           # jornada completa e decisões de projeto
```

## Onde vive o sistema real

| Caminho | Papel |
|---|---|
| `~/.config/hypr/UserScripts/RofiYtm.sh` | Interface rofi (script principal) |
| `~/.config/rofi/scripts/ytm/ytm.py` | Helper: busca/curtidas/playlists via ytmusicapi |
| `~/.config/rofi/scripts/ytm/refresh_auth.py` | Regenera headers_auth.json a partir do Firefox |
| `~/.config/rofi/scripts/ytm/headers_auth.json` | Headers autenticados (**chmod 600, nunca commitar**) |
| `~/.local/share/ytm-venv/` | venv Python (ytmusicapi, browser-cookie3, yt-dlp, plugin) |
| `~/bgutil-ytdlp-pot-provider/` | Provider de PO Token (clone + `server/node_modules`) |
| `~/.deno/` | Runtime JS do yt-dlp |
| `/tmp/ytm_songs.{tsv,lines}` | Artefatos temporários de cada listagem |

> Os caminhos acima são os **deployados** pelo `install.sh` a partir de `src/`
> (perfil do Firefox, venv e diretórios são detectados e substituídos no deploy).

## Segurança

- `headers_auth.json` contém **cookies reais de sessão** — ele fica `chmod 600`
  e **não** deve ser versionado nem compartilhado. Se vazar, revogue a sessão
  pelo navegador.
- Este repositório documenta o sistema; nenhum segredo foi commitado.