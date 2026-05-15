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

### Codespace Monitoring
- GitHub Actions workflow checks the Codespace every 8 minutes (`.github/workflows/codespace-monitor.yml`)
- Starts the Codespace if it is not already available
- Re-runs the idempotent startup script so Xray, the Telegram bot, and the keepalive loop are started only when missing
- Keeps port 443 public for the VLESS/Xray endpoint

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
- `.devcontainer/start.sh` - Idempotent startup/monitor script for Xray, bot, and keepalive
- `.github/workflows/codespace-monitor.yml` - Scheduled GitHub Actions monitor
- `.github/scripts/monitor-codespace.sh` - Codespace refresh helper used by the workflow
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

## GitHub Actions Codespace Monitor

The repository includes a scheduled workflow that requests an 8-minute monitoring cadence. GitHub Actions schedules are best-effort, so exact start times can be delayed by GitHub.

To enable it:

1. Create a GitHub personal access token with permission to manage Codespaces.
2. Add it to the repository as the secret `GH_CODESPACES_TOKEN`.
3. Optional: add a repository variable named `CODESPACE_NAME` if you want to monitor a specific Codespace. If omitted, the workflow selects the first Codespace it finds for this repository.
4. Run **Codespace monitor** manually once from the Actions tab, then let the schedule continue.

On each run, the workflow starts the Codespace if necessary, makes port 443 public, and executes the startup script. The startup script is safe to run repeatedly: it checks whether Xray, the Telegram bot, and keepalive tmux window already exist before starting anything.
