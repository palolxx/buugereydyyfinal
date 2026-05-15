#!/bin/bash
# Buugereydy start script — Xray + Telegram Bot + Keepalive
set -e

# Kill old sessions
tmux kill-session -t g2ray 2>/dev/null || true
tmux kill-session -t buugereydy 2>/dev/null || true

# Start Xray in tmux
tmux new-session -d -s g2ray
tmux send-keys -t g2ray "sudo /usr/local/bin/xray run -c /etc/xray/g2ray.json &>/tmp/xray.log" Enter
sleep 2
show-link.sh

# Xray keepalive window
tmux new-window -t g2ray -n keepalive
tmux send-keys -t g2ray:keepalive "while true; do curl -s --max-time 5 https://github.com/ -o /dev/null; sleep 180; done" Enter

# Start Telegram Bot in its own tmux
tmux new-session -d -s buugereydy
tmux send-keys -t buugereydy "cd /root/buugereydyfinal && python3 bot.py &" Enter

echo "[g2ray] Xray running in tmux g2ray"
echo "[buugereydy] Bot running in tmux buugereydy"
echo "[g2ray] Keepalive فعال است — هر 180 ثانیه یک بار ping"
