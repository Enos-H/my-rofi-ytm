#!/usr/bin/env bash
# ==================================================
#  hyprwave-panel-toggle — mostra/esconde o painel
#  do hyprwave e registra o estado manual em
#  /tmp/ytm_panel_hidden. Um +/-: o launcher
#  (RofiYtm.sh open_panel) respeita esse flag e
#  não reabre o painel se o usuário o escondeu.
# ==================================================

FLAG_FILE="/tmp/ytm_panel_hidden"

export PATH="$HOME/.local/bin:$PATH"

panel_visible() {
  hyprctl layers -j 2>/dev/null | grep -Fq '"namespace": "hyprwave"'
}

if ! pgrep -x hyprwave >/dev/null 2>&1; then
  setsid hyprwave >/dev/null 2>&1 &
  sleep 1
fi

hyprwave-toggle visibility >/dev/null 2>&1 || true

sleep 0.5

if panel_visible; then
  rm -f "$FLAG_FILE"
else
  touch "$FLAG_FILE"
fi