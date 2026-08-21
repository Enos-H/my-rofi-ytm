#!/usr/bin/env bash
# ==================================================
#  RofiYtm - YouTube Music (account) via rofi
#  Search / Liked Songs / My Playlists -> mpv
#  Backend: ytmusicapi (browser headers) + mpv + yt-dlp
#
#  Placeholders resolved by install.sh:
#    __VENV_DIR__        python venv dir (default ~/.local/share/ytm-venv)
#    __DENO_DIR__        deno install dir  (default ~/.deno)
#    __CONFIG_DIR__      config dir where helper scripts are deployed
#    __FIREFOX_PROFILE__ firefox profile with the logged-in youtube session
# ==================================================

iDIR="${XDG_CONFIG_HOME:-$HOME/.config}/swaync/icons"
rofi_theme="${XDG_CONFIG_HOME:-$HOME/.config}/rofi/config-rofi-Beats.rasi"
rofi_theme_menu="${XDG_CONFIG_HOME:-$HOME/.config}/rofi/config-rofi-Beats-menu.rasi"
PYTHON="__VENV_DIR__/bin/python"
HELPER="__CONFIG_DIR__/rofi/scripts/ytm/ytm.py"
REFRESH_AUTH="__CONFIG_DIR__/rofi/scripts/ytm/refresh_auth.py"
MPVCTL="__CONFIG_DIR__/rofi/scripts/ytm/mpvctl.py"
BRIDGE="__CONFIG_DIR__/rofi/scripts/ytm/mpris_bridge.py"
BRIDGE_PID_FILE="/tmp/ytm_bridge.pid"
PANEL_HIDDEN_FLAG="/tmp/ytm_panel_hidden"
MPV_SOCKET="/tmp/mpv-ytm.sock"
TSV_FILE="/tmp/ytm_songs.tsv"
LINES_FILE="/tmp/ytm_songs.lines"

export PATH="$HOME/.local/bin:$PATH"

notif_args=()
[ -f "$iDIR/music.png" ] && notif_args=(-i "$iDIR/music.png")

notification() {
  notify-send -u normal "${notif_args[@]}" "$@"
}

# Para a música: quit graceful pelo socket (o mpv fecha sozinho a
# conversa e remove o socket); só usa kill -9 como último recurso.
stop_music() {
  "$PYTHON" "$MPVCTL" stop >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    "$PYTHON" "$MPVCTL" ping >/dev/null 2>&1 || break
    sleep 0.1
  done
  for pid in $(pgrep -x mpv 2>/dev/null || true); do
    mpvpaper_pid=$(ps aux | grep -- 'unique-wallpaper-process' | grep -v 'grep' | awk '{print $2}')
    if ! echo "$mpvpaper_pid" | grep -q "$pid"; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
  if [ -f "$BRIDGE_PID_FILE" ]; then
    pid=$(cat "$BRIDGE_PID_FILE" 2>/dev/null) || true
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
    rm -f "$BRIDGE_PID_FILE"
  fi
  lyrics-panel-toggle close >/dev/null 2>&1 || true
  rm -f "$MPV_SOCKET"
}

# Garante o Hyprwave rodando e mostra a barra. A bridge MPRIS (nome proprio,
# preference=ytm no hyprwave) expoe titulo/art/next-prev do mpv; se ela nao
# existir, o hyprwave cai no MPRIS nativo do mpv.
open_panel() {
  local spawned=0
  if ! pgrep -x hyprwave >/dev/null 2>&1; then
    setsid hyprwave >/dev/null 2>&1 &
    sleep 1
    spawned=1
  fi
  if [ ! -f "$BRIDGE_PID_FILE" ] || ! kill -0 "$(cat "$BRIDGE_PID_FILE" 2>/dev/null)" >/dev/null 2>&1; then
    setsid env PATH="__VENV_DIR__/bin:__DENO_DIR__/bin:$PATH" "$PYTHON" "$BRIDGE" >/dev/null 2>&1 &
  fi
  if [ -f "$PANEL_HIDDEN_FLAG" ]; then
    if [ "$spawned" -eq 1 ]; then
      hyprwave-toggle visibility >/dev/null 2>&1 || true
    fi
    return 0
  fi
  misses=0
  for _ in $(seq 1 15); do
    if hyprctl layers -j 2>/dev/null | grep -Fq '"namespace": "hyprwave"'; then
      misses=0
    else
      misses=$((misses + 1))
    fi
    if [ "$misses" -ge 3 ]; then
      break
    fi
    sleep 0.2
  done
  if [ "$misses" -ge 3 ]; then
    hyprwave-toggle visibility >/dev/null 2>&1 || true
    for _ in $(seq 1 10); do
      if hyprctl layers -j 2>/dev/null | grep -Fq '"namespace": "hyprwave"'; then
        break
      fi
      sleep 0.3
    done
  fi
}

# Sobe o daemon do mpv (--idle): instancia unica, persistente. As faixas
# sao trocadas via `mpvctl load` (loadfile), entao a bridge MPRIS e o
# painel de letras NAO morrem mais entre faixas (fim do kill+restart).
# --vo=null evita o hang no teardown do wayland ao dar quit (Parar Musica).
spawn_mpv_idle() {
  # Daemon ja respondendo: reusa (instancia unica). O ping confirma que o
  # mpv esta vivo no socket, mesmo sem faixa carregada.
  if "$PYTHON" "$MPVCTL" ping >/dev/null 2>&1; then
    return 0
  fi
  # Mata daemons antigos (de spawns anteriores que ficaram para tras) para
  # nao sobrar mpv velho segurando o socket: a bridge MPRIS reconecta ao
  # novo sozinha quando a conexao do antigo cai.
  for pid in $(pgrep -x mpv 2>/dev/null || true); do
    mpvpaper_pid=$(ps aux | grep -- 'unique-wallpaper-process' | grep -v 'grep' | awk '{print $2}')
    if ! echo "$mpvpaper_pid" | grep -q "$pid"; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
  rm -f "$MPV_SOCKET"
  setsid env PATH="__VENV_DIR__/bin:__DENO_DIR__/bin:$PATH" mpv --idle --no-video --no-terminal --vo=null \
    --ytdl-format=bestaudio/best \
    --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
    --ytdl-raw-options="remote-components=ejs:github" \
    --ytdl-raw-options="cookies-from-browser=firefox:__FIREFOX_PROFILE__" \
    --input-ipc-server="$MPV_SOCKET" \
    --log-file=/tmp/ytm_mpv.log \
    >/dev/null 2>&1 &
  for _ in $(seq 1 30); do
    [ -S "$MPV_SOCKET" ] && return 0
    sleep 0.1
  done
  notification "YouTube Music" "mpv não respondeu - verifique /tmp/ytm_mpv.log"
  exit 1
}

play_url() {
  local title="$2"
  # strip do sufixo de duração "(m:ss)" se presente
  if [[ "$title" =~ ^(.*)[[:space:]]\([0-9]+:[0-9]{1,2}\)$ ]]; then
    title="${BASH_REMATCH[1]}"
  fi
  if ! "$PYTHON" "$MPVCTL" ping >/dev/null 2>&1; then
    spawn_mpv_idle
  fi
  "$PYTHON" "$MPVCTL" load "$1" replace >/dev/null 2>&1 || {
    notification "YouTube Music" "Falha ao carregar a faixa"
    exit 1
  }
  # só força o media-title quando a origem forneceu um título real
  # (playlist inteira não passa título: o nome da faixa vem do mpv/yt-dlp)
  if [[ -n "$title" ]]; then
    "$PYTHON" "$MPVCTL" title "$title" >/dev/null 2>&1 || true
  fi
  open_panel
  lyrics-panel-toggle open >/dev/null 2>&1 || true
}

# Escolhe o destino de uma faixa já selecionada: tocar agora ou enfileirar
pick_destination() {
  local url="$1" title="$2" dest
  dest=$(printf "▶️ Tocar agora\n➕ Adicionar à fila" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str "entry { placeholder: \"$title\"; }")
  [[ -z "$dest" ]] && exit 1
  case "$dest" in
  *"Tocar agora"*)
    play_url "$url" "$title"
    ;;
  *"Adicionar"*)
    if ! "$PYTHON" "$MPVCTL" ping >/dev/null 2>&1; then
      spawn_mpv_idle
    fi
    if "$PYTHON" "$MPVCTL" load "$url" append "$title" >/dev/null 2>&1; then
      notification "YouTube Music" "Na fila: $title"
    else
      notification "YouTube Music" "Falha ao adicionar à fila"
    fi
    ;;
  esac
}

# Relê os cookies do Firefox (ex.: depois de trocar de conta) e regrava headers_auth.json.
# Com 2+ contas logadas, deixa o usuário escolher qual usar (grava account_pref).
reload_cookies() {
  local out accounts n choice idx pref_file menu_file idx_file disp
  pref_file="$(dirname "$REFRESH_AUTH")/account_pref"
  out=$("$PYTHON" "$REFRESH_AUTH" --list-accounts 2>&1) || true
  accounts=$(printf '%s\n' "$out" | awk -F'\t' '$1 ~ /^[0-9]+$/ {print}')
  n=$(printf '%s\n' "$accounts" | sed '/^$/d' | wc -l)
  if [ "$n" -gt 1 ]; then
    menu_file=$(mktemp)
    idx_file=$(mktemp)
    while IFS=$'\t' read -r idx disp active; do
      [ -n "$disp" ] || continue
      if [ "$active" = "active" ]; then disp="• $disp"; fi
      printf '%s\n' "$disp" >>"$menu_file"
      printf '%s|%s\n' "$disp" "$idx" >>"$idx_file"
    done <<<"$accounts"
    choice=$(rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "👤 Escolha a conta"; }' <"$menu_file")
    idx=$(awk -F'|' -v c="$choice" '$1 == c {print $2}' "$idx_file" 2>/dev/null | head -1)
    rm -f "$menu_file" "$idx_file"
    [[ -z "$idx" ]] && exit 1
    printf '%s' "$idx" >"$pref_file"
  else
    rm -f "$pref_file"
  fi
  if ! out=$("$PYTHON" "$REFRESH_AUTH" 2>&1); then
    notify-send -u critical "${notif_args[@]}" "YouTube Music" "Falha ao recarregar cookies: $out"
    exit 1
  fi
  notification "YouTube Music" "$out"
}

# runs the python helper, echoes "TITLE<TAB>ID" so the caller can capture the
# displayed title along with the id (a $(...) subshell keeps `choice` local).
pick_from_helper() {
  local err line_num id
  if ! err=$("$PYTHON" "$HELPER" "$@" 2>&1 >/dev/null); then
    notify-send -u critical "${notif_args[@]}" "YouTube Music" "${err:-Auth error - check Firefox login}"
    exit 1
  fi
  choice=$(rofi -i -dmenu -config "$rofi_theme" -theme-str 'entry { placeholder: "🎵 Pick a song"; }' <"$LINES_FILE")
  [[ -z "$choice" ]] && exit 1
  line_num=$(grep -nFx "$choice" "$LINES_FILE" | head -1 | cut -d: -f1)
  [[ -z "$line_num" ]] && exit 1
  id=$(sed -n "${line_num}p" "$TSV_FILE" | awk -F'\t' '{print $2}')
  printf '%s\t%s\n' "$choice" "$id"
}

# Alterna a visibilidade do painel do hyprwave e registra o estado manual
toggle_panel() {
  hyprwave-panel-toggle
  if [ -f "$PANEL_HIDDEN_FLAG" ]; then
    notification "YouTube Music" "Painel escondido"
  else
    notification "YouTube Music" "Painel mostrado"
  fi
}

# Menu de letras: abrir/fechar a janela ytm-lyrics e redimensionar
lyrics_menu() {
  local sub
  sub=$(printf "🎤 Mostrar/Esconder Letras\n📐 Compacta\n📐 Média\n📐 Grande" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "🎤 Letras"; }')
  [[ -z "$sub" ]] && exit 1
  case "$sub" in
  *"Mostrar/Esconder"*) lyrics-panel-toggle visibility >/dev/null 2>&1 || true ;;
  *"Compacta"*) lyrics-panel-toggle size compacta >/dev/null 2>&1 || true ;;
  *"Média"*) lyrics-panel-toggle size media >/dev/null 2>&1 || true ;;
  *"Grande"*) lyrics-panel-toggle size grande >/dev/null 2>&1 || true ;;
  esac
}

# Converte "TITLE<TAB>ID" do pick_from_helper em "URL<TAB>TITLE" do watch
watch_from_pick() {
  local pick="$1" song_title video_id
  [[ -z "$pick" ]] && return 1
  song_title=${pick%%$'\t'*}
  video_id=${pick#*$'\t'}
  [[ -z "$video_id" ]] && return 1
  printf 'https://music.youtube.com/watch?v=%s\t%s\n' "$video_id" "$song_title"
}

# Busca uma faixa e devolve "URL<TAB>TITLE" (usado pelo search e pela fila)
pick_search_video() {
  local query song_title video_id title url
  query=$(rofi -dmenu -lines 0 -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🔎 Search YouTube Music"; }')
  [[ -z "$query" ]] && return 1
  song_title=$(pick_from_helper search "$query")
  [[ -z "$song_title" ]] && return 1
  video_id=${song_title#*$'\t'}
  song_title=${song_title%%$'\t'*}
  [[ -z "$video_id" ]] && return 1
  printf 'https://music.youtube.com/watch?v=%s\t%s\n' "$video_id" "$song_title"
}

# Search YouTube Music
search_music() {
  local hit url song_title
  hit=$(pick_search_video) || exit 1
  url=${hit%%$'\t'*}
  song_title=${hit#*$'\t'}
  pick_destination "$url" "$song_title"
}

# ------------------------------------------------------- fila e reprodução
# Loop / shuffle / fila / limpar fila
queue_loop() {
  local sub
  sub=$(printf "desligado\n1 faixa\nplaylist inteira" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "🔁 Loop"; }')
  [[ -z "$sub" ]] && exit 1
  case "$sub" in
  *"desligado"*) "$PYTHON" "$MPVCTL" loop off >/dev/null 2>&1 || true ;;
  *"1 faixa"*)   "$PYTHON" "$MPVCTL" loop track >/dev/null 2>&1 || true ;;
  *"inteira"*)   "$PYTHON" "$MPVCTL" loop playlist >/dev/null 2>&1 || true ;;
  esac
}

queue_shuffle() {
  local sub
  sub=$(printf "🔀 Ativar\n▶️ Desativar" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "🔀 Shuffle"; }')
  [[ -z "$sub" ]] && exit 1
  case "$sub" in
  *"Ativar"*)    "$PYTHON" "$MPVCTL" shuffle on >/dev/null 2>&1 || true ;;
  *"Desativar"*) "$PYTHON" "$MPVCTL" shuffle off >/dev/null 2>&1 || true ;;
  esac
}

# Mostra a fila do mpv no rofi; escolher uma linha abre um submenu de ação
queue_view() {
  local choice line_num pos qtsv qlines action
  qtsv=/tmp/ytm_queue.tsv
  qlines=/tmp/ytm_queue.lines
  if ! "$PYTHON" "$MPVCTL" queue >"$qtsv" 2>&1 || [ ! -s "$qtsv" ]; then
    notification "YouTube Music" "Fila vazia - toque uma música primeiro"
    exit 1
  fi
  cut -f2- "$qtsv" >"$qlines"
  choice=$(rofi -i -dmenu -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "📃 Fila"; }' <"$qlines")
  [[ -z "$choice" ]] && exit 1
  line_num=$(grep -nFx "$choice" "$qlines" | head -1 | cut -d: -f1)
  [[ -z "$line_num" ]] && exit 1
  pos=$(sed -n "${line_num}p" "$qtsv" | cut -f1)
  [[ -z "$pos" ]] && exit 1

  action=$(printf "▶️ Tocar agora\n⏭️ Tocar a seguir\n🗑️ Remover da fila" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "🎛️ Ação da faixa"; }')
  [[ -z "$action" ]] && exit 1
  case "$action" in
  *"Tocar agora"*)
    "$PYTHON" "$MPVCTL" play "$pos" >/dev/null 2>&1 || true
    ;;
  *"Tocar a seguir"*)
    "$PYTHON" "$MPVCTL" move "$pos" >/dev/null 2>&1 || true
    queue_view
    ;;
  *"Remover"*)
    "$PYTHON" "$MPVCTL" remove "$pos" >/dev/null 2>&1 || true
    queue_view
    ;;
  esac
}

# Menu da fila/reprodução (loop/shuffle/fila/limpar)
queue_menu() {
  local sub
  sub=$(printf "🔁 Loop\n🔀 Shuffle\n📃 Ver Fila\n🧹 Limpar fila" |
    rofi -dmenu -config "$rofi_theme_menu" \
      -theme-str 'entry { placeholder: "🎛️ Fila e Reprodução"; }')
  [[ -z "$sub" ]] && exit 1
  case "$sub" in
  *"Loop"*)         queue_loop ;;
  *"Shuffle"*)      queue_shuffle ;;
  *"Ver Fila"*)     queue_view ;;
  *"Limpar fila"*)  "$PYTHON" "$MPVCTL" clear >/dev/null 2>&1 || true; notification "YouTube Music" "Fila limpa" ;;
  esac
}

# Liked songs
liked_music() {
  local hit url song_title
  hit=$(pick_from_helper liked) || exit 1
  hit=$(watch_from_pick "$hit") || exit 1
  url=${hit%%$'\t'*}
  song_title=${hit#*$'\t'}
  pick_destination "$url" "$song_title"
}

# Library playlists
playlists_music() {
  local err
  if ! err=$("$PYTHON" "$HELPER" playlists 2>&1 >/dev/null); then
    notify-send -u critical "${notif_args[@]}" "YouTube Music" "${err:-Auth error - check Firefox login}"
    exit 1
  fi
  choice=$(rofi -i -dmenu -config "$rofi_theme" \
    -theme-str 'entry { placeholder: "📁 My Playlists"; }' <"$LINES_FILE")
  [[ -z "$choice" ]] && exit 1
  line_num=$(grep -nFx "$choice" "$LINES_FILE" | head -1 | cut -d: -f1)
  [[ -z "$line_num" ]] && exit 1
  playlist_id=$(sed -n "${line_num}p" "$TSV_FILE" | awk -F'\t' '{print $2}')

  sub_choice=$(printf "▶️  Play whole playlist\n🎵 Pick a song" | rofi -dmenu \
    -config "$rofi_theme_menu" \
    -theme-str "entry { placeholder: \"$choice\"; }")
  [[ -z "$sub_choice" ]] && exit 1

  case "$sub_choice" in
  *"whole playlist"*)
    play_url "https://music.youtube.com/playlist?list=$playlist_id" ""
    ;;
  *"Pick a song"*)
    song_title=$(pick_from_helper playlist "$playlist_id") || exit 1
    song_title=$(watch_from_pick "$song_title") || exit 1
    pick_destination "${song_title%%$'\t'*}" "${song_title#*$'\t'}"
    ;;
  esac
}

# Main menu
user_choice=$(printf "%s\n" \
  "🔎 Search YouTube Music" \
  "❤️  Liked Songs" \
  "📁 My Playlists" \
  "🎛️ Fila e Reprodução" \
  "🎤 Letras" \
  "👁️  Mostrar/Esconder Painel" \
  "⏹ Parar Música" \
  "🔄 Recarregar Cookies" |
  rofi -dmenu -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🎧 YouTube Music"; }')

case "$user_choice" in
"🔎 Search YouTube Music") search_music ;;
"❤️  Liked Songs") liked_music ;;
"📁 My Playlists") playlists_music ;;
"🎛️ Fila e Reprodução") queue_menu ;;
"🎤 Letras") lyrics_menu ;;
"👁️  Mostrar/Esconder Painel") toggle_panel ;;
"⏹ Parar Música") stop_music ;;
"🔄 Recarregar Cookies") reload_cookies ;;
esac
