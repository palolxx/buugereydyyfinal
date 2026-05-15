#!/bin/bash
# Buugereydy start script — idempotent Xray + Telegram Bot + Keepalive launcher.
set -euo pipefail

XRAY_SESSION="g2ray"
BOT_SESSION="buugereydy"
XRAY_WINDOW="xray"
KEEPALIVE_WINDOW="keepalive"
BOT_WINDOW="bot"
DEFAULT_APP_DIR="/root/buugereydyfinal"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$DEFAULT_APP_DIR" ]; then
  APP_DIR="${APP_DIR:-$DEFAULT_APP_DIR}"
else
  APP_DIR="${APP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
fi
XRAY_BIN="/usr/local/bin/xray"
XRAY_CONFIG="/etc/xray/g2ray.json"
XRAY_LOG="/tmp/xray.log"
BOT_LOG="/tmp/buugereydy-bot.log"
KEEPALIVE_INTERVAL="${KEEPALIVE_INTERVAL:-480}"

restart=0
if [ "${1:-}" = "--restart" ]; then
  restart=1
fi

if [ "$restart" -eq 1 ]; then
  tmux kill-session -t "$XRAY_SESSION" 2>/dev/null || true
  tmux kill-session -t "$BOT_SESSION" 2>/dev/null || true
fi

has_session() {
  tmux has-session -t "$1" 2>/dev/null
}

has_window() {
  tmux list-windows -t "$1" -F '#W' 2>/dev/null | grep -Fxq "$2"
}

ensure_session() {
  local session="$1"
  local window="$2"
  if ! has_session "$session"; then
    tmux new-session -d -s "$session" -n "$window"
  elif ! has_window "$session" "$window"; then
    tmux new-window -d -t "$session" -n "$window"
  fi
}

is_xray_running() {
  # Bracketed regex avoids pgrep matching its own command line.
  pgrep -f "[/]usr/local/bin/xray[[:space:]]+run[[:space:]]+-c[[:space:]]+$XRAY_CONFIG" >/dev/null 2>&1
}

is_bot_running() {
  # Bracketed regex avoids pgrep matching its own command line.
  pgrep -f "[p]ython3[[:space:]]+.*bot\.py" >/dev/null 2>&1
}

start_xray_if_needed() {
  ensure_session "$XRAY_SESSION" "$XRAY_WINDOW"
  if is_xray_running; then
    echo "[g2ray] Xray is already running."
  else
    echo "[g2ray] Starting Xray..."
    tmux send-keys -t "$XRAY_SESSION:$XRAY_WINDOW" C-c "sudo $XRAY_BIN run -c $XRAY_CONFIG &>$XRAY_LOG" Enter
    sleep 2
  fi
  show-link.sh || true
}

start_keepalive_if_needed() {
  ensure_session "$XRAY_SESSION" "$XRAY_WINDOW"
  if ! has_window "$XRAY_SESSION" "$KEEPALIVE_WINDOW"; then
    tmux new-window -d -t "$XRAY_SESSION" -n "$KEEPALIVE_WINDOW"
    tmux send-keys -t "$XRAY_SESSION:$KEEPALIVE_WINDOW" \
      "while true; do date '+[keepalive] %Y-%m-%d %H:%M:%S'; curl -s --max-time 5 https://github.com/ -o /dev/null || true; sleep $KEEPALIVE_INTERVAL; done" Enter
    echo "[g2ray] Keepalive started; ping interval is ${KEEPALIVE_INTERVAL} seconds."
  else
    echo "[g2ray] Keepalive window is already running."
  fi
}

start_bot_if_needed() {
  ensure_session "$BOT_SESSION" "$BOT_WINDOW"
  if is_bot_running; then
    echo "[buugereydy] Telegram bot is already running."
  else
    echo "[buugereydy] Starting Telegram bot..."
    tmux send-keys -t "$BOT_SESSION:$BOT_WINDOW" C-c "cd $APP_DIR && python3 bot.py &>$BOT_LOG" Enter
  fi
}

start_xray_if_needed
start_keepalive_if_needed
start_bot_if_needed

echo "[monitor] Sessions checked: $XRAY_SESSION ($XRAY_WINDOW/$KEEPALIVE_WINDOW), $BOT_SESSION ($BOT_WINDOW)."
