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

stop_music() {
  mpv_pids=$(pgrep -x mpv)
  if [ -n "$mpv_pids" ]; then
    mpvpaper_pid=$(ps aux | grep -- 'unique-wallpaper-process' | grep -v 'grep' | awk '{print $2}')
    for pid in $mpv_pids; do
      if ! echo "$mpvpaper_pid" | grep -q "$pid"; then
        kill -9 $pid || true
      fi
    done
  fi
  if [ -f "$BRIDGE_PID_FILE" ]; then
    pid=$(cat "$BRIDGE_PID_FILE" 2>/dev/null) || true
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
    rm -f "$BRIDGE_PID_FILE"
  fi
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

play_url() {
  stop_music
  local title="$2"
  [[ -z "$title" ]] && title="${choice:-YouTube Music}"
  if [[ "$title" =~ ^(.*)[[:space:]]\([0-9]+:[0-9]{1,2}\)$ ]]; then
    title="${BASH_REMATCH[1]}"
  fi
  notification "Now Playing:" "$title"
  setsid env PATH="__VENV_DIR__/bin:__DENO_DIR__/bin:$PATH" mpv --no-video --no-terminal --ytdl-format=bestaudio/best \
    --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
    --ytdl-raw-options="remote-components=ejs:github" \
    --ytdl-raw-options="cookies-from-browser=firefox:__FIREFOX_PROFILE__" \
    --input-ipc-server="$MPV_SOCKET" \
    --force-media-title="$title" \
    "$1" >/dev/null 2>&1 &
  open_panel
}

# Reabre o painel "Now Playing" se o mpv estiver vivo
nowplaying() {
  if ! "$PYTHON" "$MPVCTL" ping; then
    notification "YouTube Music" "Nada tocando no momento"
    exit 1
  fi
  open_panel
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

# Search YouTube Music
search_music() {
  query=$(rofi -dmenu -lines 0 -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🔎 Search YouTube Music"; }')
  [[ -z "$query" ]] && exit 1
  song_title=$(pick_from_helper search "$query")
  [[ -z "$song_title" ]] && exit 1
  video_id=${song_title#*$'\t'}
  song_title=${song_title%%$'\t'*}
  [[ -z "$video_id" ]] && exit 1
  play_url "https://music.youtube.com/watch?v=$video_id" "$song_title"
}

# Liked songs
liked_music() {
  song_title=$(pick_from_helper liked)
  [[ -z "$song_title" ]] && exit 1
  video_id=${song_title#*$'\t'}
  song_title=${song_title%%$'\t'*}
  [[ -z "$video_id" ]] && exit 1
  play_url "https://music.youtube.com/watch?v=$video_id" "$song_title"
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
    play_url "https://music.youtube.com/playlist?list=$playlist_id" "$choice"
    ;;
  *"Pick a song"*)
    song_title=$(pick_from_helper playlist "$playlist_id")
    [[ -z "$song_title" ]] && exit 1
    video_id=${song_title#*$'\t'}
    song_title=${song_title%%$'\t'*}
    [[ -z "$video_id" ]] && exit 1
    play_url "https://music.youtube.com/watch?v=$video_id" "$song_title"
    ;;
  esac
}

# Main menu
user_choice=$(printf "%s\n" \
  "🔎 Search YouTube Music" \
  "❤️  Liked Songs" \
  "📁 My Playlists" \
  "🎧 Now Playing" \
  "👁️  Mostrar/Esconder Painel" \
  "🔄 Recarregar Cookies" |
  rofi -dmenu -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🎧 YouTube Music"; }')

case "$user_choice" in
"🔎 Search YouTube Music") search_music ;;
"❤️  Liked Songs") liked_music ;;
"📁 My Playlists") playlists_music ;;
"🎧 Now Playing") nowplaying ;;
"👁️  Mostrar/Esconder Painel") toggle_panel ;;
"🔄 Recarregar Cookies") reload_cookies ;;
esac
