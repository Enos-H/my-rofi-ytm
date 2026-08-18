# rofi-ytm

**YouTube Music (da sua conta) dentro do rofi.**

Pesquise músicas no catálogo do YouTube Music, acesse suas curtidas e
playlists, escolha a faixa com o rofi e toque no `mpv` — tudo 100% teclado,
sem abrir navegador nem interface gráfica de música. A reprodução é
acompanhada por um painel "Now Playing" (Hyprwave) e por um painel de
letras em karaokê ANSI.

```text
rofi ─▶ ytmusicapi (sua conta) ─▶ mpv + yt-dlp ─▶ Hyprwave (painel) + kitty (letras)
```

## Funcionalidades em uma linha

- 🔎 **Search** — busca no catálogo completo do YouTube Music
- ❤️ **Liked Songs** — suas músicas curtidas
- 📁 **My Playlists** — todas as playlists (tocar inteira ou escolher faixa)
- 🎧 **Now Playing** — painel Hyprwave com título real, thumbnail, progresso,
  volume e controles play/pause/próxima/anterior (em playlists)
- 🎛️ **Fila e Reprodução** — tocar a seguir (fila), loop (off/1 faixa/playlist),
  shuffle e ver a fila do mpv
- 🎤 **Letras** — karaokê ANSI sincronizado (lrclib.net) numa janela kitty
- 👁️ **Mostrar/Esconder Painel** — oculta o painel mantendo a música
- ⏹ **Parar Música** — encerra o mpv de forma limpa (quit pelo socket)
- 🔄 **Recarregar Cookies** — renova a autenticação e troca de conta
  (seletor quando há 2+ contas logadas no Firefox)

## Atalhos

| Atalho | Ação |
|---|---|
| `SUPER SHIFT Y` | Abre o menu YouTube Music |
| `SUPER CTRL Y` | Mostra/esconde o painel do Hyprwave (adicionado pelo instalador) |
| `SUPER CTRL L` | Abre/fecha o painel de letras (adicionado pelo instalador) |

## Instalação

Pré-requisitos: rofi, mpv, libnotify, Firefox logado no YouTube e Python 3.10+.

```bash
./install.sh                 # instala deps (sudo), venv, deno, provider,
                             # detecta o perfil Firefox e deploya tudo de src/
./install.sh --hyprwave      # (também) builda o Hyprwave + keybinds do painel
./install.sh --help          # todas as opções
```

Suporta Ubuntu/Debian (apt), Arch (pacman) e Fedora (dnf). O instalador
adiciona os keybinds `SUPER CTRL Y` / `SUPER CTRL L` e as windowrules da
janela de letras no `Keybinds.conf`/`WindowRules.conf` do Hyprland
(idempotente). Sem o Hyprwave a música toca normalmente — só o painel não
abre.

## Documentação

| Doc | Conteúdo |
|---|---|
| [`docs/01-overview.md`](docs/01-overview.md) | Visão geral e todas as funcionalidades |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Arquitetura completa, dependências, integrações e o ambiente onde roda |
| [`docs/03-authentication.md`](docs/03-authentication.md) | Autenticação (headers do navegador + SAPISIDHASH + multi-conta) |
| [`docs/04-playback.md`](docs/04-playback.md) | Playback (PO Token, deno, yt-dlp, mpv, conta free) |
| [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) | Problemas comuns e correções |
| [`docs/06-history.md`](docs/06-history.md) | Jornada do projeto e decisões |
| [`docs/07-now-playing-panel.md`](docs/07-now-playing-panel.md) | Painel "Now Playing" (Hyprwave + bridge MPRIS) |
| [`docs/08-lyrics-panel.md`](docs/08-lyrics-panel.md) | Painel de letras (karaokê ANSI) |

## Estrutura

```text
rofi-ytm/
├── install.sh                  # instalador reproduzível (deps, venv, deploy, keybinds)
├── src/                        # fontes (deployados pelo install.sh)
│   ├── RofiYtm.sh              # interface rofi (launcher)
│   ├── ytm.py                  # helper da API (busca/curtidas/playlists)
│   ├── refresh_auth.py         # regenerador de credencial (cookies do Firefox)
│   ├── mpvctl.py               # cliente do socket JSON do mpv (daemon --idle)
│   ├── mpris_bridge.py         # player MPRIS (org.mpris.MediaPlayer2.ytm;
│   │                           #   conexão persistente + eventos, retry, caches)
│   ├── hyprwave-panel-toggle.sh    # mostra/esconde o painel
│   ├── lyrics_player.py        # karaokê ANSI das letras (lrclib.net + cache)
│   ├── lyrics-panel-toggle.sh  # abre/fecha/redimensiona a janela de letras
│   └── hyprwave/               # config + patches do Hyprwave (build)
└── docs/                       # documentação (índice acima)
```

## Segurança

`headers_auth.json` contém cookies reais de sessão — fica `chmod 600` e
nunca é versionado nem compartilhado (`.gitignore` cobre os dois arquivos
sensíveis). Se vazar, revogue a sessão pelo navegador.
