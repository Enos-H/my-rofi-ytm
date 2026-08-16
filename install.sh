#!/usr/bin/env bash
# ==================================================
#  RofiYtm installer
#  Reproduces the full YouTube Music via rofi setup
#  on a fresh system (Ubuntu/Debian, Arch, Fedora).
#
#  See docs/02-architecture.md -> "Instalador (install.sh)"
# ==================================================
set -euo pipefail

VERSION="1.0.0"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$REPO_DIR/src"

DENO_INSTALL_DIR="${DENO_INSTALL:-$HOME/.deno}"
VENV_DIR="${YTM_VENV:-$HOME/.local/share/ytm-venv}"
CONFIG_DIR="${YTM_CONFIG_DIR:-$HOME/.config}"
PROVIDER_DIR="${YTM_PROVIDER_DIR:-$HOME/bgutil-ytdlp-pot-provider}"
PROVIDER_REPO="https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"

OPT_PROFILE=""
OPT_NO_DEPS=0
OPT_SKIP_VERIFY=0
OPT_UNINSTALL=0
OPT_HYPRWAVE=0

say()  { printf '\033[1;32m[rofi-ytm]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[rofi-ytm]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[rofi-ytm]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: install.sh [options]

Options:
  --profile <dir>      Firefox profile to use (overrides auto-detection)
  --prefix <dir>       Python venv dir (default: \$HOME/.local/share/ytm-venv)
  --config-dir <dir>   Config dir for deployed scripts (default: \$HOME/.config)
  --no-deps           Skip installing system packages (rofi, mpv, node, python...)
  --hyprwave          Also build/install the hyprwave Now Playing panel
  --skip-verify       Skip the final search / PO-token verification
  --uninstall         Remove everything this installer created
  -h, --help          Show this help

Env vars: YTM_PROFILE, YTM_VENV, YTM_CONFIG_DIR, YTM_PROVIDER_DIR, DENO_INSTALL
EOF
}

confirm() {
  printf '%s [y/N] ' "$*"
  read -r ans
  [[ "$ans" =~ ^[Yy](es)?$ ]]
}

# ---------------------------------------------------------------- distro
detect_distro() {
  local id
  id="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-unknown}" || printf 'unknown')"
  case "$id" in
    ubuntu|debian|linuxmint|pop|elementary|zorin) echo apt ;;
    arch|manjaro|endeavouros|cachyos)             echo pacman ;;
    fedora|rocky|centos|rhel)                     echo dnf ;;
    *)                                            echo unknown ;;
  esac
}

# binary_name:apt:pacman:dnf
DEPS_MAP=(
  "rofi:rofi:rofi:rofi"
  "mpv:mpv:mpv:mpv"
  "notify-send:libnotify-bin:libnotify:libnotify"
  "git:git:git:git"
  "curl:curl:curl:curl"
  "node:npm:npm:npm"
  "npm:npm:npm:npm"
  "python3:python3:python:python3"
  "python3-venv:python3-venv:python-virtualenv:python3-virtualenv"
)

install_system_deps() {
  local distro missing=() bin pkg_apt pkg_pacman pkg_dnf pkg
  distro="$(detect_distro)"
  [[ "$distro" == "unknown" ]] && die "distro desconhecida - instale rofi, mpv, libnotify, git, curl, nodejs, npm e python3-venv manualmente, ou use --no-deps"

  for entry in "${DEPS_MAP[@]}"; do
    IFS=':' read -r bin pkg_apt pkg_pacman pkg_dnf <<<"$entry"
    [[ "$bin" == "python3-venv" ]] && { command -v python3 >/dev/null && python3 -m venv --help >/dev/null 2>&1 && continue; }
    if ! command -v "$bin" >/dev/null 2>&1; then
      case "$distro" in
        apt)    pkg="$pkg_apt" ;;
        pacman) pkg="$pkg_pacman" ;;
        dnf)    pkg="$pkg_dnf" ;;
      esac
      missing+=("$pkg")
    fi
  done
  [[ ${#missing[@]} -eq 0 ]] && return 0

  say "pacotes necessários: ${missing[*]}"
  confirm "Instalar com sudo?" || die "instalação abortada (use --no-deps para pular)"
  sudo -v

  case "$distro" in
    apt)    sudo apt-get update -y && sudo apt-get install -y "${missing[@]}" ;;
    pacman) sudo pacman -S --noconfirm --needed "${missing[@]}" ;;
    dnf)    sudo dnf install -y "${missing[@]}" ;;
  esac
}

# Deps do painel "Now Playing" (hyprwave) - opcionais, só avisam
check_panel_deps() {
  command -v hyprwave >/dev/null 2>&1 && return 0
  warn "hyprwave não encontrado - o painel de controle não aparece"
  warn "  (instale com: $0 --hyprwave, ou manual: sudo apt install libgtk4-layer-shell-dev + make install)"
}

# ----------------------------------------------------------------- hyprwave
# Painel de controle "Now Playing" (MPRIS) - build automático:
#   sudo apt install libgtk4-layer-shell-dev; git clone; make; PREFIX make install
install_hyprwave() {
  if command -v hyprwave >/dev/null 2>&1; then
    say "hyprwave já instalado ($(command -v hyprwave))"
  else
    [[ "$OPT_NO_DEPS" -eq 1 ]] && { warn "pulando hyprwave (--no-deps)"; return; }
    command -v git >/dev/null || die "git é necessário para instalar o hyprwave"
    local distro
    distro="$(detect_distro)"
    case "$distro" in
      apt)    sudo apt-get install -y libgtk4-layer-shell-dev ;;
      pacman) sudo pacman -S --noconfirm --needed gtk4-layer-shell ;;
      dnf)    sudo dnf install -y gtk4-layer-shell-devel ;;
    esac
    local tmp
    tmp=$(mktemp -d)
    say "clonando hyprwave (shantanubaddar/hyprwave) ..."
    git clone --depth 1 https://github.com/shantanubaddar/hyprwave.git "$tmp/hyprwave"
    # patches custom do hyprwave (git apply de todos os *.patch de src/hyprwave):
    # - hyprwave-reconnect.patch: re-seleciona o player preferido quando um novo
    #   player MPRIS aparece (senão o hyprwave fica preso no MPRIS nativo do
    #   mpv e nunca troca para a bridge "ytm")
    # - hyprwave-art.patch: preserva a proporção da arte e usa COVER no box
    #   principal (thumbnail 16:9 não fica espremida nem com faixas laterais)
    # - hyprwave-jitter.patch: ondas estáveis (ring buffer + smoothing) e
    #   container limitado ao rodapé da control bar (painel no tamanho original)
    local applied_patch=0
    for p in "$SRC_DIR"/hyprwave/*.patch; do
      [ -f "$p" ] || continue
      if (cd "$tmp/hyprwave" && git apply "$p"); then
        say "patch do hyprwave aplicado: $(basename "$p")"
        applied_patch=1
      else
        warn "falha ao aplicar $(basename "$p")"
      fi
    done
    if [ "$applied_patch" -eq 0 ]; then
      warn "nenhum patch do hyprwave aplicado (players preferidos podem não re-selecionar; arte pode distorcer)"
    fi
    (cd "$tmp/hyprwave" && make all && PREFIX="$HOME/.local" make install)
    say "hyprwave instalado em $HOME/.local/bin"
  fi

  # config.conf: bridge "ytm" primeiro na preferência de players (hyprwave usa a bridge)
  mkdir -p "$HOME/.config/hyprwave"
  if [ ! -f "$HOME/.config/hyprwave/config.conf" ]; then
    if [ -f "$SRC_DIR/hyprwave/config.conf" ]; then
      install -m 644 "$SRC_DIR/hyprwave/config.conf" "$HOME/.config/hyprwave/config.conf"
    else
      cat > "$HOME/.config/hyprwave/config.conf" <<'EOF'
[General]
edge=top
margin=10
layer=top
exclusive_zone=0

[Notifications]
enabled=true
now_playing=true

[Visualizer]
enabled=true
idle_timeout=5

[VerticalDisplay]
enabled=false
idle_timeout=5

[MusicPlayer]
preference=ytm,mpv,spotify,vlc
EOF
    fi
    say "config do hyprwave gerado em ~/.config/hyprwave/config.conf"
  else
    say "config do hyprwave já existe (mantido)"
  fi
}

# ------------------------------------------------------------------ deno
install_deno() {
  if [ -x "$DENO_INSTALL_DIR/bin/deno" ]; then
    say "deno já instalado ($( "$DENO_INSTALL_DIR/bin/deno" --version 2>/dev/null | head -1))"
    return
  fi
  say "instalando deno em $DENO_INSTALL_DIR ..."
  command -v curl >/dev/null || die "curl é necessário (instale ou use --no-deps)"
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL="$DENO_INSTALL_DIR" sh -s -- -y
}

# ------------------------------------------------------------------ venv
install_venv() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    say "venv já existe em $VENV_DIR (pip packages serão atualizados)"
  else
    say "criando venv em $VENV_DIR ..."
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv "$VENV_DIR"
  fi
  say "instalando ytmusicapi, browser-cookie3, yt-dlp, provider bgutil e dbus-next (bridge MPRIS) ..."
  "$VENV_DIR/bin/pip" install --upgrade ytmusicapi browser-cookie3 yt-dlp bgutil-ytdlp-pot-provider dbus-next
}

# --------------------------------------------------------------- provider
install_provider() {
  command -v git >/dev/null || die "git é necessário (instale ou use --no-deps)"
  if [ -d "$PROVIDER_DIR/.git" ]; then
    say "provider já clonado em $PROVIDER_DIR"
    git -C "$PROVIDER_DIR" pull --ff-only >/dev/null 2>&1 || warn "git pull do provider falhou (continuando)"
  else
    say "clonando $PROVIDER_REPO ..."
    git clone --depth 1 "$PROVIDER_REPO" "$PROVIDER_DIR"
  fi

  if [ ! -d "$PROVIDER_DIR/server/node_modules" ]; then
    command -v npm >/dev/null || die "npm é necessário (instale ou use --no-deps)"
    say "npm ci em $PROVIDER_DIR/server ..."
    (cd "$PROVIDER_DIR/server" && npm ci --frozen-lockfile)
  else
    say "node_modules do provider já presentes"
  fi

  warmup_provider
}

# first deno run downloads deps; warm the cache so the 15s plugin timeout
# never trips on the first real playback
warmup_provider() {
  local cache="$HOME/.cache/bgutil-ytdlp-pot-provider"
  say "pré-compilando provider (primeira execução do deno) ..."
  "$DENO_INSTALL_DIR/bin/deno" run \
    --allow-env --allow-net \
    --allow-ffi="$PROVIDER_DIR/server/node_modules" \
    --allow-write="$cache" \
    --allow-read="$cache,$PROVIDER_DIR/server/node_modules" \
    "$PROVIDER_DIR/server/src/generate_once.ts" --version >/dev/null 2>&1 \
    || warn "warmup falhou - a primeira reprodução pode demorar mais que o normal"
}

# ------------------------------------------------------------ firefox profile
newest_profile() {
  ls -dt "$@" 2>/dev/null | head -1
}

valid_profile() {
  [ -f "$1/cookies.sqlite" ] && [ -f "$1/key4.db" ]
}

detect_profile() {
  local p
  if [ -n "$OPT_PROFILE" ]; then
    p="$OPT_PROFILE"
  elif [ -n "${YTM_PROFILE:-}" ]; then
    p="$YTM_PROFILE"
  else
    p="$(newest_profile "$HOME"/snap/firefox/common/.mozilla/firefox/*.default*)"
    [ -z "$p" ] && p="$(newest_profile "$HOME"/.mozilla/firefox/*.default*)"
    [ -z "$p" ] && p="$(newest_profile "$HOME"/.var/app/org.mozilla.firefox/.mozilla/firefox/*.default*)"
  fi
  valid_profile "$p" 2>/dev/null || die "perfil Firefox não encontrado/validado ($p).
  Use --profile <dir> com cookies.sqlite+key4.db, ou abra o Firefox e logue em youtube.com."
  say "perfil Firefox: $p"
  FIREFOX_PROFILE="$p"
}

# ------------------------------------------------------------------ deploy
deploy_scripts() {
  local ytm_dir="$CONFIG_DIR/rofi/scripts/ytm"
  local hypr_dir="$CONFIG_DIR/hypr/UserScripts"
  local target

  mkdir -p "$ytm_dir"
  install -m 755 "$SRC_DIR/ytm.py" "$ytm_dir/ytm.py"
  install -m 755 "$SRC_DIR/refresh_auth.py" "$ytm_dir/refresh_auth.py"
  sed -i "s|__FIREFOX_PROFILE__|$FIREFOX_PROFILE|g" "$ytm_dir/refresh_auth.py"

  if [ -d "$CONFIG_DIR/hypr" ]; then
    mkdir -p "$hypr_dir"
    target="$hypr_dir/RofiYtm.sh"
  else
    mkdir -p "$HOME/.local/bin"
    target="$HOME/.local/bin/RofiYtm.sh"
  fi
  install -m 755 "$SRC_DIR/RofiYtm.sh" "$target"
  sed -i \
    -e "s|__VENV_DIR__|$VENV_DIR|g" \
    -e "s|__DENO_DIR__|$DENO_INSTALL_DIR|g" \
    -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
    -e "s|__FIREFOX_PROFILE__|$FIREFOX_PROFILE|g" \
    "$target"

  # mpvctl (cliente do socket JSON do mpv) - usado pelo launcher (Now Playing)
  install -m 755 "$SRC_DIR/mpvctl.py" "$ytm_dir/mpvctl.py"
  say "mpvctl:   $ytm_dir/mpvctl.py"

  # bridge MPRIS (org.mpris.MediaPlayer2.ytm) - titulo real + thumbnail + next/prev
  if [ -f "$SRC_DIR/mpris_bridge.py" ]; then
    install -m 755 "$SRC_DIR/mpris_bridge.py" "$ytm_dir/mpris_bridge.py"
    sed -i "s|__FIREFOX_PROFILE__|$FIREFOX_PROFILE|g" "$ytm_dir/mpris_bridge.py"
    say "bridge:   $ytm_dir/mpris_bridge.py"
  else
    warn "src/mpris_bridge.py ausente - hyprwave sem titulo real/thumbnail/next-prev"
  fi

  # toggle de visibilidade do painel (respeita o estado manual via /tmp/ytm_panel_hidden)
  if [ -f "$SRC_DIR/hyprwave-panel-toggle.sh" ]; then
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$SRC_DIR/hyprwave-panel-toggle.sh" "$HOME/.local/bin/hyprwave-panel-toggle"
    say "toggle:   $HOME/.local/bin/hyprwave-panel-toggle"
  else
    warn "src/hyprwave-panel-toggle.sh ausente - não será possível esconder/mostrar o painel do menu"
  fi

  # painel de letras (karaokê ANSI em uma janela kitty dedicada)
  if [ -f "$SRC_DIR/lyrics_player.py" ]; then
    install -m 755 "$SRC_DIR/lyrics_player.py" "$ytm_dir/lyrics_player.py"
    say "lyrics:   $ytm_dir/lyrics_player.py"
  else
    warn "src/lyrics_player.py ausente - painel de letras não será deployado"
  fi
  if [ -f "$SRC_DIR/lyrics-panel-toggle.sh" ]; then
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$SRC_DIR/lyrics-panel-toggle.sh" "$HOME/.local/bin/lyrics-panel-toggle"
    sed -i \
      -e "s|__VENV_DIR__|$VENV_DIR|g" \
      -e "s|__DENO_DIR__|$DENO_INSTALL_DIR|g" \
      -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
      "$HOME/.local/bin/lyrics-panel-toggle"
    say "lyrics toggle: $HOME/.local/bin/lyrics-panel-toggle"
  else
    warn "src/lyrics-panel-toggle.sh ausente - não será possível abrir/fechar as letras"
  fi

  # rofi themes (KoolDots) ausentes -> remove os -config, usa o tema padrão
  if ! ls "$CONFIG_DIR"/rofi/config-rofi-Beats*.rasi >/dev/null 2>&1; then
    sed -i -E 's/ -config "\$rofi_theme(_menu)?"//g' "$target"
    warn "temas config-rofi-Beats*.rasi não encontrados - usando tema padrão do rofi"
  fi

  say "scripts deployados:"
  say "  helper:  $ytm_dir/{ytm.py,refresh_auth.py}"
  say "  launcher:$target"
}

# -------------------------------------------------------------------- auth
bootstrap_auth() {
  say "gerando headers_auth.json a partir do Firefox ..."
  if "$VENV_DIR/bin/python" "$CONFIG_DIR/rofi/scripts/ytm/refresh_auth.py"; then
    say "autenticação OK"
  else
    warn "autenticação falhou - logue em youtube.com no Firefox e rode:"
    warn "  $VENV_DIR/bin/python $CONFIG_DIR/rofi/scripts/ytm/refresh_auth.py"
  fi
}

# ----------------------------------------------------------------- verify
verify_install() {
  local test_id="4KLVnmChtIE"
  local out lines
  say "verificando API (busca de teste) ..."
  out="$("$VENV_DIR/bin/python" "$CONFIG_DIR/rofi/scripts/ytm/ytm.py" search "test" 2>&1 || true)"
  lines="$(printf '%s\n' "$out" | wc -l)"
  if [ "$lines" -ge 1 ] && ! grep -q "auth error" <<<"$out"; then
    say "API OK ($lines resultados)"
  else
    warn "busca de teste falhou: $(head -1 <<<"$out")"
  fi

  say "verificando provider de PO token (extração real) ..."
  out="$(PATH="$VENV_DIR/bin:$DENO_INSTALL_DIR/bin:$PATH" yt-dlp -v --simulate --print '%(url)s' -f bestaudio/best \
    --extractor-args "youtube:player_client=web_music" \
    --remote-components "ejs:github" \
    --cookies-from-browser "firefox:$FIREFOX_PROFILE" \
    "https://music.youtube.com/watch?v=$test_id" 2>&1 || true)"
  if grep -q 'pot=' <<<"$out"; then
    say "PO token provider OK (bgutil + pot= confirmado)"
  elif grep -q 'PO Token Providers: bgutil' <<<"$out"; then
    warn "bgutil carregado, mas URL sem pot= - pode ser instabilidade do YouTube"
  else
    warn "bgutil não detectado pelo yt-dlp - rode: $VENV_DIR/bin/pip install -U bgutil-ytdlp-pot-provider"
    warn "$(tail -3 <<<"$out")"
  fi
}

# ----------------------------------------------------------------- keybind
print_keybind_help() {
  cat <<EOF

Para ativar o atalho, adicione UMA das linhas abaixo na sua config do Hyprland:

  # em hyprland.conf  (ou em um arquivo incluído, ex.: Keybinds.conf)
  bindd = \$mainMod SHIFT, Y, YouTube Music, exec, $([[ -d "$CONFIG_DIR/hypr" ]] && echo "$CONFIG_DIR/hypr/UserScripts/RofiYtm.sh" || echo "$HOME/.local/bin/RofiYtm.sh")

Depois recarregue:
  hyprctl reload
EOF
}

# ------------------------------------------------------- keybind (toggle painel)
setup_toggle_keybind() {
  local kb="$CONFIG_DIR/hypr/configs/Keybinds.conf"
  local line
  if [ ! -f "$HOME/.local/bin/hyprwave-panel-toggle" ]; then
    warn "toggle do painel não deployado - pulando keybind SUPER+CTRL+Y"
    return
  fi
  if [ ! -f "$kb" ]; then
    say "Keybinds.conf do Hyprland não encontrado ($kb) - keybind do painel não adicionado"
    return
  fi
  if grep -qF 'Toggle YTM panel' "$kb"; then
    say "keybind SUPER+CTRL+Y (toggle painel) já presente no Keybinds.conf"
    return
  fi
  line="bindd = \$mainMod CTRL, Y, Toggle YTM panel, exec, $HOME/.local/bin/hyprwave-panel-toggle"
  printf '\n# rofi-ytm: mostra/esconde o painel do hyprwave\n%s\n' "$line" >>"$kb"
  say "keybind SUPER+CTRL+Y adicionado no Keybinds.conf (recarregue com hyprctl reload)"
}

# ------------------------------------------------- keybinds (painel de letras)
setup_lyrics_bindings() {
  local wr="$CONFIG_DIR/hypr/configs/WindowRules.conf"
  local kb="$CONFIG_DIR/hypr/configs/Keybinds.conf"
  local rules=(
    "windowrule {"
    "    name = ytm lyrics"
    "    match:class = ^(ytm-lyrics)\$"
    "    float = on"
    "    size = 420 300"
    "    move = 1155 42"
    "    pin = on"
    "    no_initial_focus = on"
    "}"
  )
  if [ ! -f "$HOME/.local/bin/lyrics-panel-toggle" ]; then
    warn "lyrics-panel-toggle não deployado - pulando windowrules/keybind das letras"
    return
  fi
  if [ -f "$wr" ]; then
    if grep -qF 'ytm-lyrics' "$wr"; then
      say "windowrules do painel de letras já presentes no WindowRules.conf"
    else
      printf '\n# rofi-ytm: painel de letras (karaokê ANSI)\n' >>"$wr"
      printf '%s\n' "${rules[@]}" >>"$wr"
      say "windowrules do painel de letras adicionados no WindowRules.conf"
    fi
  else
    warn "WindowRules.conf do Hyprland não encontrado ($wr) - adicione manualmente:"
    printf '  %s\n' "${rules[@]}"
  fi
  if [ -f "$kb" ]; then
    if grep -qF 'Toggle YTM lyrics' "$kb"; then
      say "keybind SUPER+CTRL+L (letras) já presente no Keybinds.conf"
    else
      printf '\n# rofi-ytm: abre/fecha o painel de letras\nbindd = $mainMod CTRL, L, Toggle YTM lyrics, exec, $HOME/.local/bin/lyrics-panel-toggle visibility\n' >>"$kb"
      say "keybind SUPER+CTRL+L adicionado no Keybinds.conf (recarregue com hyprctl reload)"
    fi
  else
    warn "Keybinds.conf do Hyprland não encontrado ($kb) - keybind das letras não adicionado"
  fi
}

# ---------------------------------------------------------------- uninstall
uninstall() {
  local ytm_dir="$CONFIG_DIR/rofi/scripts/ytm"
  local launcher
  if [ -d "$CONFIG_DIR/hypr" ]; then
    launcher="$CONFIG_DIR/hypr/UserScripts/RofiYtm.sh"
  else
    launcher="$HOME/.local/bin/RofiYtm.sh"
  fi

  cat <<EOF
Serão removidos:
  venv:            $VENV_DIR
  provider:        $PROVIDER_DIR
  helper scripts:  $ytm_dir   (inclui mpvctl.py e a bridge mpris_bridge.py)
  launcher:        $launcher
EOF
  confirm "Confirmar remoção?" || die "uninstall abortado"
  rm -rf "$VENV_DIR" "$PROVIDER_DIR" "$ytm_dir" "$launcher"
  rm -f "$HOME/.local/bin/hyprwave-panel-toggle"
  rm -f "$HOME/.local/bin/lyrics-panel-toggle"
  rm -f /tmp/mpv-ytm.sock /tmp/ytm_bridge.pid /tmp/ytm_panel_hidden /tmp/ytm_lyrics.pid
  pkill -f "ytm/mpris_bridge" 2>/dev/null || true
  pkill -f "[y]tm-lyrics" 2>/dev/null || true
  if [ -f "$CONFIG_DIR/hypr/configs/Keybinds.conf" ]; then
    sed -i '/Toggle YTM panel/d;/Toggle YTM lyrics/d;/rofi-ytm: mostra\/esconde o painel do hyprwave/d;/rofi-ytm: abre\/fecha o painel de letras/d' \
      "$CONFIG_DIR/hypr/configs/Keybinds.conf" 2>/dev/null || true
    say "keybinds do painel/letras removidos do Keybinds.conf"
  fi
  if [ -f "$CONFIG_DIR/hypr/configs/WindowRules.conf" ]; then
    sed -i '/rofi-ytm: painel de letras (karaokê ANSI)/,/}/d' \
      "$CONFIG_DIR/hypr/configs/WindowRules.conf" 2>/dev/null || true
    say "windowrules do painel de letras removidas do WindowRules.conf"
  fi
  say "removido."
}

# ------------------------------------------------------------------- main
main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --profile)    OPT_PROFILE="$2"; shift 2 ;;
      --prefix)     VENV_DIR="$2"; shift 2 ;;
      --config-dir) CONFIG_DIR="$2"; shift 2 ;;
      --no-deps)    OPT_NO_DEPS=1; shift ;;
      --skip-verify) OPT_SKIP_VERIFY=1; shift ;;
      --uninstall)  OPT_UNINSTALL=1; shift ;;
      --hyprwave)   OPT_HYPRWAVE=1; shift ;;
      -h|--help)    usage; exit 0 ;;
      *)            die "opção desconhecida: $1 (use --help)" ;;
    esac
  done

  [ -d "$SRC_DIR" ] || die "src/ não encontrado - rode o instalador a partir do repo rofi-ytm"

  if [ "$OPT_UNINSTALL" -eq 1 ]; then
    uninstall
    exit 0
  fi

  say "RofiYtm installer v$VERSION"
  [[ "$OPT_NO_DEPS" -eq 0 ]] && install_system_deps
  check_panel_deps
  [[ "$OPT_HYPRWAVE" -eq 1 ]] && install_hyprwave
  install_deno
  install_venv
  install_provider
  detect_profile
  deploy_scripts
  setup_toggle_keybind
  setup_lyrics_bindings
  bootstrap_auth
  [[ "$OPT_SKIP_VERIFY" -eq 0 ]] && verify_install
  print_keybind_help

  say "concluído. Teste com: $([[ -d "$CONFIG_DIR/hypr" ]] && echo "$CONFIG_DIR/hypr/UserScripts/RofiYtm.sh" || echo "$HOME/.local/bin/RofiYtm.sh")"
}

main "$@"