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
  say "instalando ytmusicapi, browser-cookie3, yt-dlp e o provider bgutil ..."
  "$VENV_DIR/bin/pip" install --upgrade ytmusicapi browser-cookie3 yt-dlp bgutil-ytdlp-pot-provider
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
  helper scripts:  $ytm_dir
  launcher:        $launcher
EOF
  confirm "Confirmar remoção?" || die "uninstall abortado"
  rm -rf "$VENV_DIR" "$PROVIDER_DIR" "$ytm_dir" "$launcher"
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
  install_deno
  install_venv
  install_provider
  detect_profile
  deploy_scripts
  bootstrap_auth
  [[ "$OPT_SKIP_VERIFY" -eq 0 ]] && verify_install
  print_keybind_help

  say "concluído. Teste com: $([[ -d "$CONFIG_DIR/hypr" ]] && echo "$CONFIG_DIR/hypr/UserScripts/RofiYtm.sh" || echo "$HOME/.local/bin/RofiYtm.sh")"
}

main "$@"