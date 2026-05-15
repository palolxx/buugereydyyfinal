# BUUGEREYDY VPN Manager

Full Telegram management system for Xray (V2Ray) servers running on GitHub Codespaces.

## Features

### User Management
- Create users with unique UUIDs
- Set data limits (1GB, 3GB, 5GB, 10GB, or custom MB)
- Set expiry dates (1 day, 3 days, 1 week, 1 month, 3 months, 6 months, 1 year, or custom date)
- Enable/disable users
- Blacklist individual users
- Reset user data usage
- Delete users

### Chain Proxy Support
- HTTP proxy chain
- SOCKS5 proxy chain
- Per-user chain proxy configuration
- Global chain proxy for all users

### Analytics
- Total user count
- Active/expired/limited user counts
- Data usage per user (with percentages)
- Top consumers ranking
- CSV export

### Config Management
- Generate all user links
- Export config as JSON
- Backup/restore Xray config
- Reload config without restart
- Restart/stop/start Xray

### Blacklist
- Domain blacklist (via regex)
- IP blacklist
- Per-user blacklist
- Toggle ads, bittorrent, private IP blocking

### Settings
- DNS provider selection (Cloudflare, Google, Quad9, custom)
- Port selection (443, 8443, 2053, 2087)
- Network selection (xhttp, grpc, websocket, tcp)
- Security selection (none, tls, xtls)
- Transport mode (packet-up, xudp, header, gun)
- Sniffing toggle
- Add admin users

### Codespace Keepalive
- Automatic ping every 10 minutes to prevent 4-hour timeout
- Xray keepalive via tmux session

## Telegram Commands

- `/start` - Start the bot
- `/menu` - Show main menu
- `/add` - Quick add user
- `/analytics` - Quick analytics
- `/stats` - Server stats
- `/help` - Help

## Files

- `bot.py` - Main Telegram bot
- `xray_manager.py` - Xray config management
- `database.py` - SQLite database
- `requirements.txt` - Python dependencies
- `.devcontainer/Dockerfile` - Container image
- `.devcontainer/start.sh` - Startup script
- `.devcontainer/config.json` - Xray config (original format)

## Config Format

The Xray config format is preserved exactly:
- VLESS protocol
- xhttp transport
- DNS with Cloudflare DoH
- Routing rules (private IPs, bittorrent, ads)
- Policy settings

## Deployment

1. Push to GitHub
2. Open in GitHub Codespace
3. Codespace automatically builds Docker image and starts Xray + Bot
4. Bot becomes available on Telegram
