#!/usr/bin/env bash
# ==================================================
#  lyrics-panel-toggle — abre/fecha a janela de
#  letras (kitty --class ytm-lyrics) e ajusta o
#  tamanho dela no Hyprland.
#
#  Uso:
#    lyrics-panel-toggle visibility   # abre se fechada, fecha se aberta
#    lyrics-panel-toggle close        # fecha se aberta
#    lyrics-panel-toggle size compacta|media|grande
# ==================================================

PYTHON="__VENV_DIR__/bin/python"
LYRICS_PLAYER="__CONFIG_DIR__/rofi/scripts/ytm/lyrics_player.py"
LYRICS_PID_FILE="/tmp/ytm_lyrics.pid"

export PATH="$HOME/.local/bin:$PATH"

SIZE_W_COMPACTA=520
SIZE_H_COMPACTA=300
SIZE_W_MEDIA=600
SIZE_H_MEDIA=400
SIZE_W_GRANDE=800
SIZE_H_GRANDE=600

lyrics_alive() {
  [ -f "$LYRICS_PID_FILE" ] || return 1
  kill -0 "$(cat "$LYRICS_PID_FILE" 2>/dev/null)" >/dev/null 2>&1
}

lyrics_address() {
  hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for c in d:
    if c.get('class') == 'ytm-lyrics':
        print(c.get('address', ''))
        sys.exit(0)
sys.exit(1)
"
}

open_lyrics() {
  if lyrics_alive; then
    return 0
  fi
  setsid env PATH="__VENV_DIR__/bin:__DENO_DIR__/bin:$PATH" \
    kitty --class ytm-lyrics --title "Letras" -e "$PYTHON" "$LYRICS_PLAYER" \
    >/dev/null 2>&1 &
  echo $! >"$LYRICS_PID_FILE"
  sleep 1
  return 0
}

close_lyrics() {
  local addr pid
  addr=$(lyrics_address)
  if [ -n "$addr" ]; then
    hyprctl dispatch closewindow "address:$addr" >/dev/null 2>&1 || true
  fi
  pid=$(cat "$LYRICS_PID_FILE" 2>/dev/null) || true
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
  rm -f "$LYRICS_PID_FILE"
  return 0
}

set_size() {
  local label="$1" w h addr
  case "$label" in
  compacta | compact | small)
    w=$SIZE_W_COMPACTA
    h=$SIZE_H_COMPACTA
    ;;
  media | medium)
    w=$SIZE_W_MEDIA
    h=$SIZE_H_MEDIA
    ;;
  grande | large)
    w=$SIZE_W_GRANDE
    h=$SIZE_H_GRANDE
    ;;
  *)
    echo "tamanho invalido: $label (use compacta|media|grande)" >&2
    exit 1
    ;;
  esac
  addr=$(lyrics_address)
  if [ -z "$addr" ]; then
    echo "janela de letras nao esta aberta" >&2
    exit 1
  fi
  hyprctl dispatch resizewindowpixel exact "$w" "$h,address:$addr" >/dev/null 2>&1
  return 0
}

action="${1:-visibility}"
case "$action" in
visibility | toggle)
  if lyrics_alive || [ -n "$(lyrics_address)" ]; then
    close_lyrics
  else
    open_lyrics
  fi
  ;;
open | show)
  open_lyrics
  ;;
close | hide)
  close_lyrics
  ;;
size)
  set_size "$2"
  ;;
*)
  echo "acao invalida: $action" >&2
  exit 1
  ;;
esac