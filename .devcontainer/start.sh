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
KEEPALIVE_LOG="/tmp/buugereydy-keepalive.log"
KEEPALIVE_PID="/tmp/buugereydy-keepalive.pid"
KEEPALIVE_INTERVAL="${KEEPALIVE_INTERVAL:-480}"

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

if command -v tmux >/dev/null 2>&1; then
  HAS_TMUX=1
else
  HAS_TMUX=0
  echo "[monitor] tmux is not installed; using background-process fallback."
fi

restart=0
if [ "${1:-}" = "--restart" ]; then
  restart=1
fi

if [ "$restart" -eq 1 ] && [ "$HAS_TMUX" -eq 1 ]; then
  tmux kill-session -t "$XRAY_SESSION" 2>/dev/null || true
  tmux kill-session -t "$BOT_SESSION" 2>/dev/null || true
fi

has_session() {
  [ "$HAS_TMUX" -eq 1 ] && tmux has-session -t "$1" 2>/dev/null
}

has_window() {
  [ "$HAS_TMUX" -eq 1 ] && tmux list-windows -t "$1" -F '#W' 2>/dev/null | grep -Fxq "$2"
}

ensure_session() {
  local session="$1"
  local window="$2"
  if [ "$HAS_TMUX" -ne 1 ]; then
    return 0
  fi
  if ! has_session "$session"; then
    tmux new-session -d -s "$session" -n "$window"
  elif ! has_window "$session" "$window"; then
    tmux new-window -d -t "$session" -n "$window"
  fi
}

pid_file_running() {
  local pid_file="$1"
  [ -s "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

run_detached() {
  local session="$1"
  local window="$2"
  local command="$3"
  local log_file="$4"

  if [ "$HAS_TMUX" -eq 1 ]; then
    ensure_session "$session" "$window"
    tmux send-keys -t "$session:$window" C-c "$command >\"$log_file\" 2>&1" Enter
  else
    nohup bash -lc "$command" >"$log_file" 2>&1 &
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
    run_detached "$XRAY_SESSION" "$XRAY_WINDOW" "$SUDO $XRAY_BIN run -c $XRAY_CONFIG" "$XRAY_LOG"
    sleep 2
  fi
  if command -v show-link.sh >/dev/null 2>&1; then
    show-link.sh || true
  elif [ -x "$SCRIPT_DIR/show-link.sh" ]; then
    "$SCRIPT_DIR/show-link.sh" || true
  fi
}

start_keepalive_if_needed() {
  ensure_session "$XRAY_SESSION" "$XRAY_WINDOW"
  if [ "$HAS_TMUX" -eq 1 ]; then
    if ! has_window "$XRAY_SESSION" "$KEEPALIVE_WINDOW"; then
      tmux new-window -d -t "$XRAY_SESSION" -n "$KEEPALIVE_WINDOW"
      tmux send-keys -t "$XRAY_SESSION:$KEEPALIVE_WINDOW" \
        "while true; do date '+[keepalive] %Y-%m-%d %H:%M:%S'; curl -s --max-time 5 https://github.com/ -o /dev/null || true; sleep $KEEPALIVE_INTERVAL; done" Enter
      echo "[g2ray] Keepalive started; ping interval is ${KEEPALIVE_INTERVAL} seconds."
    else
      echo "[g2ray] Keepalive window is already running."
    fi
  elif pid_file_running "$KEEPALIVE_PID"; then
    echo "[g2ray] Keepalive process is already running."
  else
    echo "[g2ray] Starting keepalive background process..."
    nohup bash -lc "while true; do date '+[keepalive] %Y-%m-%d %H:%M:%S'; curl -s --max-time 5 https://github.com/ -o /dev/null || true; sleep $KEEPALIVE_INTERVAL; done" >"$KEEPALIVE_LOG" 2>&1 &
    echo $! >"$KEEPALIVE_PID"
  fi
}

start_bot_if_needed() {
  ensure_session "$BOT_SESSION" "$BOT_WINDOW"
  if is_bot_running; then
    echo "[buugereydy] Telegram bot is already running."
  else
    echo "[buugereydy] Starting Telegram bot..."
    run_detached "$BOT_SESSION" "$BOT_WINDOW" "cd $APP_DIR && python3 bot.py" "$BOT_LOG"
  fi
}

start_xray_if_needed
start_keepalive_if_needed
start_bot_if_needed

if [ "$HAS_TMUX" -eq 1 ]; then
  echo "[monitor] Sessions checked: $XRAY_SESSION ($XRAY_WINDOW/$KEEPALIVE_WINDOW), $BOT_SESSION ($BOT_WINDOW)."
else
  echo "[monitor] Background processes checked. Logs: $XRAY_LOG, $BOT_LOG, $KEEPALIVE_LOG."
fi
