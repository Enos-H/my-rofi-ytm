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
TSV_FILE="/tmp/ytm_songs.tsv"
LINES_FILE="/tmp/ytm_songs.lines"

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
}

play_url() {
  stop_music
  notification "Now Playing:" "${choice:-YouTube Music}"
  setsid env PATH="__VENV_DIR__/bin:__DENO_DIR__/bin:$PATH" mpv --no-video --no-terminal --ytdl-format=bestaudio/best \
    --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
    --ytdl-raw-options="remote-components=ejs:github" \
    --ytdl-raw-options="cookies-from-browser=firefox:__FIREFOX_PROFILE__" \
    "$1" >/dev/null 2>&1 &
}

# runs the python helper, returns the rofi-selected line id
pick_from_helper() {
  local err
  if ! err=$("$PYTHON" "$HELPER" "$@" 2>&1 >/dev/null); then
    notify-send -u critical "${notif_args[@]}" "YouTube Music" "${err:-Auth error - check Firefox login}"
    exit 1
  fi
  choice=$(rofi -i -dmenu -config "$rofi_theme" -theme-str 'entry { placeholder: "🎵 Pick a song"; }' <"$LINES_FILE")
  [[ -z "$choice" ]] && exit 1
  line_num=$(grep -nFx "$choice" "$LINES_FILE" | head -1 | cut -d: -f1)
  [[ -z "$line_num" ]] && exit 1
  sed -n "${line_num}p" "$TSV_FILE" | awk -F'\t' '{print $2}'
}

# Search YouTube Music
search_music() {
  query=$(rofi -dmenu -lines 0 -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🔎 Search YouTube Music"; }')
  [[ -z "$query" ]] && exit 1
  video_id=$(pick_from_helper search "$query")
  [[ -z "$video_id" ]] && exit 1
  play_url "https://music.youtube.com/watch?v=$video_id"
}

# Liked songs
liked_music() {
  video_id=$(pick_from_helper liked)
  [[ -z "$video_id" ]] && exit 1
  play_url "https://music.youtube.com/watch?v=$video_id"
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
    play_url "https://music.youtube.com/playlist?list=$playlist_id"
    ;;
  *"Pick a song"*)
    video_id=$(pick_from_helper playlist "$playlist_id")
    [[ -z "$video_id" ]] && exit 1
    play_url "https://music.youtube.com/watch?v=$video_id"
    ;;
  esac
}

# Main menu
user_choice=$(printf "%s\n" \
  "🔎 Search YouTube Music" \
  "❤️  Liked Songs" \
  "📁 My Playlists" |
  rofi -dmenu -config "$rofi_theme_menu" \
    -theme-str 'entry { placeholder: "🎧 YouTube Music"; }')

case "$user_choice" in
"🔎 Search YouTube Music") search_music ;;
"❤️  Liked Songs") liked_music ;;
"📁 My Playlists") playlists_music ;;
esac