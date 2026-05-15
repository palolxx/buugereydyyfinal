import os
import sys
import time
import uuid
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import database as db
import xray_manager as xray

TOKEN = "8709950346:AAFTsalOIaTnp9IxMb31gPWsedRTwpSdtpE"

def fmt_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    if b < 1024**3: return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.1f} GB"

def fmt_mb(mb):
    if mb < 1024: return f"{mb:.0f} MB"
    return f"{mb/1024:.1f} GB"

def fmt_time(ts):
    if not ts: return "Never"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def calculate_expiry(dur):
    now = datetime.now()
    if dur.endswith("d"):
        return (now + timedelta(days=int(dur[:-1]))).strftime("%Y-%m-%d")
    elif dur.endswith("w"):
        return (now + timedelta(weeks=int(dur[:-1]))).strftime("%Y-%m-%d")
    elif dur.endswith("m"):
        month = now.month + int(dur[:-1])
        year = now.year + month // 12
        month = month % 12 or 12
        return f"{year}-{month:02d}-01"
    elif dur.endswith("y"):
        return f"{now.year + int(dur[:-1])}-01-01"
    return dur

# === MARKUP BUILDERS ===

def main_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add User", callback_data="add_user"),
         InlineKeyboardButton("All Users", callback_data="all_users")],
        [InlineKeyboardButton("User Analytics", callback_data="analytics")],
        [InlineKeyboardButton("Config Management", callback_data="config_mgmt")],
        [InlineKeyboardButton("Blacklist", callback_data="blacklist"),
         InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("Server Stats", callback_data="server_stats")],
    ])

def add_user_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Data Limit", callback_data="au_limit")],
        [InlineKeyboardButton("Expiry Date", callback_data="au_expiry")],
        [InlineKeyboardButton("Chain Proxy", callback_data="au_chain")],
        [InlineKeyboardButton("Done & Create", callback_data="au_done")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ])

def user_detail_markup(email):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Edit Limit", callback_data=f"edit_limit:{email}")],
        [InlineKeyboardButton("Edit Expiry", callback_data=f"edit_expiry:{email}")],
        [InlineKeyboardButton("Toggle Block", callback_data=f"toggle_block:{email}")],
        [InlineKeyboardButton("Reset Data", callback_data=f"reset_data:{email}")],
        [InlineKeyboardButton("Toggle Enable/Disable", callback_data=f"toggle_enable:{email}")],
        [InlineKeyboardButton("View Share Link", callback_data=f"view_link:{email}")],
        [InlineKeyboardButton("Delete User", callback_data=f"del_user:{email}")],
        [InlineKeyboardButton("Back to Users", callback_data="all_users")],
    ])

def settings_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Chain Proxy", callback_data="set_chain")],
        [InlineKeyboardButton("DNS Provider", callback_data="set_dns")],
        [InlineKeyboardButton("Domain Blacklist", callback_data="set_domain_bl")],
        [InlineKeyboardButton("Routing Rules", callback_data="set_routing")],
        [InlineKeyboardButton("Server Settings", callback_data="set_server")],
        [InlineKeyboardButton("Backup / Restore", callback_data="set_backup")],
        [InlineKeyboardButton("Add Admin", callback_data="set_admin")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ])

def chain_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("HTTP Proxy", callback_data="chain_http")],
        [InlineKeyboardButton("SOCKS5 Proxy", callback_data="chain_socks")],
        [InlineKeyboardButton("Remove Chain", callback_data="chain_remove")],
        [InlineKeyboardButton("Current Value", callback_data="chain_current")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ])

def admin_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])

# === TEXT HELPERS ===

def user_detail_text(user):
    limit_str = fmt_mb(user["data_limit_mb"]) if user["data_limit_mb"] else "Unlimited"
    return (
        f"User: {user['email']}\n\n"
        f"UUID: {user['uuid']}\n"
        f"Enabled: {'Yes' if user['enabled'] else 'No'}\n"
        f"Blacklisted: {'Yes' if user['blacklist'] else 'No'}\n"
        f"Data Limit: {limit_str}\n"
        f"Data Used: {fmt_mb(user['data_used_mb'])}\n"
        f"Expiry: {user.get('expiry_date') or 'No expiry'}\n"
        f"Created: {fmt_time(user['created_at'])}\n"
        f"Chain Proxy: {user.get('chain_proxy') or 'None'}"
    )

def config_link(email, uuid_val):
    info = xray.get_link_info()
    if not info:
        return "Link unavailable"
    return (
        f"vless://{uuid_val}@94.130.50.12:443?"
        f"encryption=none&security=tls&sni={info['sni']}"
        f"&host={info['host']}&fp=chrome&allowInsecure=1"
        f"&type={info['network']}&mode={info['mode']}&path=%2F#{email}"
    )

# === CALLBACK HANDLER ===

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    msg = query.message

    if data == "back":
        await msg.edit_text("Main menu:", reply_markup=main_markup())
        return

    # --- Add User flow ---
    if data == "add_user":
        await msg.edit_text(
            "Create new user\n\n"
            "1. Set data limit\n"
            "2. Set expiry date\n"
            "3. Set chain proxy\n"
            "4. Done - generates config",
            reply_markup=add_user_markup())
        return

    if data == "au_limit":
        context.user_data["_au_step"] = "limit"
        kb = InlineKeyboardMarkup([
            *[InlineKeyboardButton(f"{p}GB", callback_data=f"au_lp:{p*1024}") for p in [1,3,5,10,20,50]],
            [InlineKeyboardButton("Custom (MB)", callback_data="au_lc")],
            [InlineKeyboardButton("Unlimited", callback_data="au_ln")],
            [InlineKeyboardButton("Back", callback_data="add_user")],
        ])
        await msg.edit_text("Data limit (MB)\n\nSelect preset or enter custom:", reply_markup=kb)
        return

    if data.startswith("au_lp:"):
        mb = int(data.split(":")[1])
        context.user_data["_au_limit"] = mb
        await msg.edit_text(f"Limit: {fmt_mb(mb)}\n\nSet expiry:")
        return

    if data == "au_lc":
        context.user_data["_au_step"] = "au_lc"
        await msg.edit_text("Enter custom limit in MB:")
        return

    if data == "au_ln":
        context.user_data["_au_limit"] = 0
        await msg.edit_text("Unlimited.\n\nSet expiry:")
        return

    if data == "au_expiry":
        context.user_data["_au_step"] = "expiry"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1D", callback_data="au_ep:1d"),
             InlineKeyboardButton("3D", callback_data="au_ep:3d")],
            [InlineKeyboardButton("1W", callback_data="au_ep:1w"),
             InlineKeyboardButton("2W", callback_data="au_ep:2w")],
            [InlineKeyboardButton("1M", callback_data="au_ep:1m"),
             InlineKeyboardButton("3M", callback_data="au_ep:3m")],
            [InlineKeyboardButton("6M", callback_data="au_ep:6m"),
             InlineKeyboardButton("1Y", callback_data="au_ep:1y")],
            [InlineKeyboardButton("Custom", callback_data="au_ec")],
            [InlineKeyboardButton("None", callback_data="au_en")],
            [InlineKeyboardButton("Back", callback_data="add_user")],
        ])
        await msg.edit_text("Expiry date\n\nSelect duration:", reply_markup=kb)
        return

    if data.startswith("au_ep:"):
        dur = data.split(":")[1]
        context.user_data["_au_expiry"] = calculate_expiry(dur)
        await msg.edit_text(f"Expiry: {context.user_data['_au_expiry']}\nSet chain or tap Done.")
        return

    if data == "au_ec":
        context.user_data["_au_step"] = "au_ec"
        await msg.edit_text("Enter date (YYYY-MM-DD):")
        return

    if data == "au_en":
        context.user_data["_au_expiry"] = None
        await msg.edit_text("No expiry.\nSet chain or tap Done.")
        return

    if data == "au_chain":
        context.user_data["_au_step"] = "chain"
        await msg.edit_text("Chain proxy for this user:\n\n"
            "Format: http://user:pass@host:port\n"
            "Or: socks://host:port\n\nEmpty = direct.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="add_user")]]))
        return

    if data == "au_done":
        email = context.user_data.get("_au_email", "user_" + str(uuid.uuid4())[:4])
        limit = context.user_data.get("_au_limit", 0)
        expiry = context.user_data.get("_au_expiry")
        chain = context.user_data.get("_au_chain", "")
        new_uuid = str(uuid.uuid4())
        db.add_user(new_uuid, email, limit, expiry, chain)
        xray.reload_xray()
        link = config_link(email, new_uuid)
        await msg.edit_text(
            f"User created: {email}\n\n"
            f"UUID: {new_uuid}\n"
            f"Limit: {fmt_mb(limit)}\n"
            f"Expiry: {expiry or 'Never'}\n"
            f"Chain: {chain or 'None'}\n\n"
            f"Link: {link[:120]}...",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("All Users", callback_data="all_users"),
                InlineKeyboardButton("Main Menu", callback_data="back")
            ]]))
        context.user_data.clear()
        return

    # --- All Users ---
    if data == "all_users":
        users = db.get_all_users()
        if not users:
            await msg.edit_text("No users yet.")
            return
        total = len(users)
        enabled = sum(1 for u in users if u["enabled"])
        expired = sum(1 for u in users if u.get("expiry_date") and datetime.strptime(u["expiry_date"], "%Y-%m-%d") < datetime.now())
        limited = sum(1 for u in users if u["data_limit_mb"] > 0)
        text = (f"All Users ({total})\nEnabled: {enabled} | Expired: {expired} | Limited: {limited}\n\n"
                f"Tap a user:")
        kb = [[InlineKeyboardButton(u["email"], callback_data=f"user_detail:{u['email']}")] for u in users[:30]]
        kb.append([InlineKeyboardButton("Back", callback_data="back")])
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("user_detail:"):
        email = data.split(":")[1]
        user = db.get_user_by_email(email)
        if not user:
            await msg.edit_text("User not found.")
            return
        await msg.edit_text(user_detail_text(user), reply_markup=user_detail_markup(email))
        return

    if data.startswith("edit_limit:"):
        email = data.split(":")[1]
        user = db.get_user_by_email(email)
        kb = InlineKeyboardMarkup([
            *[InlineKeyboardButton(f"{p}GB", callback_data=f"limit_set:{email}:{p*1024}") for p in [1,3,5,10,20,50,100]],
            [InlineKeyboardButton("Custom", callback_data=f"limit_custom:{email}")],
            [InlineKeyboardButton("Unlimited", callback_data=f"limit_unset:{email}")],
            [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
        ])
        await msg.edit_text(f"Limit for {email}\nCurrent: {fmt_mb(user['data_limit_mb']) if user['data_limit_mb'] else 'Unlimited'}\nUsed: {fmt_mb(user['data_used_mb'])}\n\nSelect:", reply_markup=kb)
        return

    if data.startswith("limit_set:"):
        parts = data.split(":")
        db.update_user_by_email(parts[1], data_limit_mb=int(parts[2]))
        xray.reload_xray()
        await msg.edit_text(f"Limit set: {fmt_mb(int(parts[2]))} for {parts[1]}")
        return

    if data.startswith("limit_custom:"):
        email = data.split(":")[1]
        context.user_data["_edit_email"] = email
        context.user_data["_au_step"] = "edit_limit_custom"
        await msg.edit_text(f"Enter limit in MB for {email}:")
        return

    if data.startswith("limit_unset:"):
        email = data.split(":")[1]
        db.update_user_by_email(email, data_limit_mb=0)
        xray.reload_xray()
        await msg.edit_text(f"Unlimited for {email}")
        return

    if data.startswith("edit_expiry:"):
        email = data.split(":")[1]
        user = db.get_user_by_email(email)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1D", callback_data=f"exp_set:{email}:1d")],
            [InlineKeyboardButton("3D", callback_data=f"exp_set:{email}:3d")],
            [InlineKeyboardButton("1W", callback_data=f"exp_set:{email}:1w")],
            [InlineKeyboardButton("2W", callback_data=f"exp_set:{email}:2w")],
            [InlineKeyboardButton("1M", callback_data=f"exp_set:{email}:1m")],
            [InlineKeyboardButton("3M", callback_data=f"exp_set:{email}:3m")],
            [InlineKeyboardButton("6M", callback_data=f"exp_set:{email}:6m")],
            [InlineKeyboardButton("1Y", callback_data=f"exp_set:{email}:1y")],
            [InlineKeyboardButton("Custom", callback_data=f"exp_custom:{email}")],
            [InlineKeyboardButton("Remove", callback_data=f"exp_unset:{email}")],
            [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
        ])
        await msg.edit_text(f"Expiry for {email}\nCurrent: {user.get('expiry_date') or 'No expiry'}\n\nSelect:", reply_markup=kb)
        return

    if data.startswith("exp_set:"):
        parts = data.split(":")
        db.update_user_by_email(parts[1], expiry_date=calculate_expiry(parts[2]))
        xray.reload_xray()
        await msg.edit_text(f"Expiry set: {db.get_user_by_email(parts[1])['expiry_date']} for {parts[1]}")
        return

    if data.startswith("exp_custom:"):
        email = data.split(":")[1]
        context.user_data["_edit_email"] = email
        context.user_data["_au_step"] = "edit_exp_custom"
        await msg.edit_text(f"Enter date (YYYY-MM-DD) for {email}:")
        return

    if data.startswith("exp_unset:"):
        email = data.split(":")[1]
        db.update_user_by_email(email, expiry_date=None)
        xray.reload_xray()
        await msg.edit_text(f"Expiry removed for {email}")
        return

    # --- Toggle actions ---
    if data.startswith("toggle_block:"):
        email = data.split(":")[1]
        u = db.get_user_by_email(email)
        db.update_user_by_email(email, blacklist=0 if u["blacklist"] else 1)
        xray.reload_xray()
        await msg.edit_text(f"{'Blacklisted' if not u['blacklist'] else 'Unblocked'}: {email}")
        return

    if data.startswith("reset_data:"):
        email = data.split(":")[1]
        db.update_user_by_email(email, data_used_mb=0)
        await msg.edit_text(f"Data reset: {email}")
        return

    if data.startswith("toggle_enable:"):
        email = data.split(":")[1]
        u = db.get_user_by_email(email)
        db.update_user_by_email(email, enabled=0 if u["enabled"] else 1)
        xray.reload_xray()
        await msg.edit_text(f"{'Enabled' if not u['enabled'] else 'Disabled'}: {email}")
        return

    if data.startswith("view_link:"):
        email = data.split(":")[1]
        u = db.get_user_by_email(email)
        if not u:
            await msg.edit_text("User not found.")
            return
        link = config_link(email, u["uuid"])
        await msg.edit_text(f"Config for {email}:\n\n{link}\n\nShare with user.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))
        return

    if data.startswith("del_user:"):
        email = data.split(":")[1]
        u = db.get_user_by_email(email)
        if u:
            db.delete_user_by_email(email)
            xray.reload_xray()
            await msg.edit_text(f"Deleted: {email}")
        else:
            await msg.edit_text("Not found.")
        return

    # --- Analytics ---
    if data == "analytics":
        users = db.get_all_users()
        if not users:
            await msg.edit_text("No users.")
            return
        total = len(users)
        enabled = sum(1 for u in users if u["enabled"])
        expired = sum(1 for u in users if u.get("expiry_date") and datetime.strptime(u["expiry_date"], "%Y-%m-%d") < datetime.now())
        limited = sum(1 for u in users if u["data_limit_mb"] > 0)
        total_used = sum(u["data_used_mb"] for u in users)
        top = sorted(users, key=lambda u: u["data_used_mb"], reverse=True)[:5]
        text = (f"Analytics\n\nTotal: {total} | Active: {enabled} | Expired: {expired}\n"
                f"Limited: {limited}\nTotal Used: {fmt_mb(total_used)}\n\nTop:\n")
        for i, u in enumerate(top, 1):
            pct = f" ({u['data_used_mb']/u['data_limit_mb']*100:.0f}%)" if u["data_limit_mb"] else ""
            text += f"{i}. {u['email']}: {fmt_mb(u['data_used_mb'])}{pct}\n"
        text += "\n"
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("All Users", callback_data="all_users"),
             InlineKeyboardButton("Export CSV", callback_data="export_csv")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]))
        return

    if data == "export_csv":
        users = db.get_all_users()
        csv = "Email,UUID,Limit(MB),Used(MB),Expiry,Enabled,Blacklist\n"
        for u in users:
            csv += f"{u['email']},{u['uuid']},{u['data_limit_mb']},{u['data_used_mb']},{u['expiry_date'] or ''},{u['enabled']},{u['blacklist']}\n"
        Path("/tmp/users.csv").write_text(csv)
        await msg.reply_text("CSV exported. Download via repo: /tmp/users.csv")
        return

    # --- Config Management ---
    if data == "config_mgmt":
        config = xray.generate_config()
        links = xray.get_all_links()
        text = (f"Config Management\n\n"
                f"Users: {len(links)}\n"
                f"Config: /etc/xray/g2ray.json\n"
                f"Xray Running: {xray.check_xray_running()}\n\n"
                f"Actions:")
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Generate All Links", callback_data="gen_links")],
            [InlineKeyboardButton("All Users", callback_data="all_users")],
            [InlineKeyboardButton("Export JSON", callback_data="export_config")],
            [InlineKeyboardButton("Reload Config", callback_data="reload_config")],
            [InlineKeyboardButton("Backup/Restore", callback_data="set_backup")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]))
        return

    if data == "gen_links":
        links = xray.get_all_links()
        if not links:
            await msg.edit_text("No links.")
            return
        text = f"Links ({len(links)})\n\n"
        for l in links[:5]:
            text += f"{l['email']}: {l['link'][:80]}...\n"
        if len(links) > 5:
            text += f"\n... +{len(links)-5} more"
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("All Links (all)", callback_data="all_links")],
            [InlineKeyboardButton("Back", callback_data="config_mgmt")],
        ]))
        return

    if data == "all_links":
        links = xray.get_all_links()
        if not links:
            await msg.edit_text("No links.")
            return
        for i in range(0, len(links), 40):
            batch = links[i:i+40]
            for l in batch:
                await msg.reply_text(f"{l['email']}:\n{l['link']}")
        await msg.edit_text("Links sent.")
        return

    if data == "export_config":
        config = xray.generate_config()
        Path("/tmp/config.json").write_text(json.dumps(config, indent=2))
        await msg.edit_text("Config saved to /tmp/config.json")
        return

    if data == "reload_config":
        xray.reload_xray()
        await msg.edit_text("Reloaded!")

    # --- Blacklist ---
    if data == "blacklist":
        await msg.edit_text("Blacklist", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Domain Blacklist", callback_data="bl_domains")],
            [InlineKeyboardButton("IP Blacklist", callback_data="bl_ips")],
            [InlineKeyboardButton("Blacklisted Users", callback_data="bl_users")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]))
        return

    if data == "bl_domains":
        domains = db.get_blacklist("domain")
        text = f"Domain Blacklist ({len(domains)})\n\n"
        text += "\n".join(f"- {d['value']}" for d in domains[:50]) if domains else "Empty."
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add", callback_data="bl_add_domain")],
            [InlineKeyboardButton("Back", callback_data="blacklist")],
        ]))
        return

    if data == "bl_add_domain":
        context.user_data["_bl_type"] = "domain"
        await msg.edit_text("Enter domain to blacklist (e.g. google.com):\nType 'back' to return.")
        return

    if data == "bl_ips":
        ips = db.get_blacklist("ip")
        text = f"IP Blacklist ({len(ips)})\n\n"
        text += "\n".join(f"- {i['value']}" for i in ips[:50]) if ips else "Empty."
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add", callback_data="bl_add_ip")],
            [InlineKeyboardButton("Back", callback_data="blacklist")],
        ]))
        return

    if data == "bl_add_ip":
        context.user_data["_bl_type"] = "ip"
        await msg.edit_text("Enter IP/range (e.g. 1.1.1.1):\nType 'back' to return.")
        return

    if data == "bl_users":
        users = db.get_all_users()
        bl = [u for u in users if u["blacklist"]]
        text = f"Blacklisted Users ({len(bl)})\n\n"
        text += "\n".join(f"- {u['email']}" for u in bl[:50]) if bl else "None."
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="blacklist")]]))
        return

    # --- Settings ---
    if data == "settings":
        await msg.edit_text("Settings", reply_markup=settings_markup())
        return

    if data == "set_chain":
        await msg.edit_text("Chain Proxy", reply_markup=chain_markup())
        return

    if data == "chain_current":
        chain = db.get_setting("chain_proxy")
        await msg.edit_text(f"Current: {chain or 'None'}")
        return

    if data == "chain_http":
        context.user_data["_chain_type"] = "http"
        await msg.edit_text("HTTP proxy:\nhttp://user:pass@host:port\nType 'back' to return.")
        return

    if data == "chain_socks":
        context.user_data["_chain_type"] = "socks"
        await msg.edit_text("SOCKS5 proxy:\nsocks://host:port\nType 'back' to return.")
        return

    if data == "chain_remove":
        db.set_setting("chain_proxy", "")
        xray.reload_xray()
        await msg.edit_text("Chain removed.")
        return

    if data == "set_dns":
        current = db.get_setting("dns_server") or "https://1.1.1.1/dns-query"
        await msg.edit_text(f"Current DNS: {current}\n\nSelect:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cloudflare", callback_data="dns_cf")],
            [InlineKeyboardButton("Google", callback_data="dns_google")],
            [InlineKeyboardButton("Quad9", callback_data="dns_quad9")],
            [InlineKeyboardButton("Custom", callback_data="dns_custom")],
            [InlineKeyboardButton("Back", callback_data="settings")],
        ]))
        return

    if data == "dns_cf":
        db.set_setting("dns_server", "https://1.1.1.1/dns-query")
        xray.reload_xray()
        await msg.edit_text("DNS: Cloudflare")
    elif data == "dns_google":
        db.set_setting("dns_server", "https://dns.google/dns-query")
        xray.reload_xray()
        await msg.edit_text("DNS: Google")
    elif data == "dns_quad9":
        db.set_setting("dns_server", "https://dns.quad9.net/dns-query")
        xray.reload_xray()
        await msg.edit_text("DNS: Quad9")
    elif data == "dns_custom":
        context.user_data["_dns_type"] = "custom"
        await msg.edit_text("Custom DNS URL:\nType 'back' to return.")
        return

    if data == "set_domain_bl":
        await msg.edit_text("Domain Blacklist", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add", callback_data="bl_add_domain")],
            [InlineKeyboardButton("View All", callback_data="bl_domains")],
            [InlineKeyboardButton("Back", callback_data="settings")],
        ]))
        return

    if data == "set_routing":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'OFF' if db.get_setting('bittorrent_block')=='0' else 'ON'} Bittorrent", callback_data="route_bt"),
             InlineKeyboardButton(f"{'OFF' if db.get_setting('ads_block')=='0' else 'ON'} Ads", callback_data="route_ads")],
            [InlineKeyboardButton(f"{'OFF' if db.get_setting('private_ip_block')=='0' else 'ON'} Private IPs", callback_data="route_priv"),
             InlineKeyboardButton(f"{'OFF' if db.get_setting('sniffing_enabled')=='0' else 'ON'} Sniffing", callback_data="route_sniff")],
            [InlineKeyboardButton("Back", callback_data="settings")],
        ])
        await msg.edit_text("Toggle routing rules:", reply_markup=kb)
        return

    if data == "route_bt":
        db.set_setting("bittorrent_block", "0")
        xray.reload_xray()
        await msg.edit_text("BT block OFF")
    elif data == "route_ads":
        db.set_setting("ads_block", "0")
        xray.reload_xray()
        await msg.edit_text("Ads block OFF")
    elif data == "route_priv":
        db.set_setting("private_ip_block", "0")
        xray.reload_xray()
        await msg.edit_text("Private IP block OFF")
    elif data == "route_sniff":
        db.set_setting("sniffing_enabled", "0")
        xray.reload_xray()
        await msg.edit_text("Sniffing OFF")

    # --- Server Settings ---
    if data == "set_server":
        await msg.edit_text("Server Settings", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Port: {db.get_setting('xray_port') or '443'}", callback_data="ss_port")],
            [InlineKeyboardButton(f"Network: {db.get_setting('xray_network') or 'xhttp'}", callback_data="ss_net")],
            [InlineKeyboardButton(f"Security: {db.get_setting('xray_security') or 'none'}", callback_data="ss_sec")],
            [InlineKeyboardButton(f"Mode: {db.get_setting('xray_mode') or 'packet-up'}", callback_data="ss_mode")],
            [InlineKeyboardButton("Restart Xray", callback_data="restart_xray"),
             InlineKeyboardButton("Stop", callback_data="stop_xray")],
            [InlineKeyboardButton("Start", callback_data="start_xray")],
            [InlineKeyboardButton("Back", callback_data="settings")],
        ]))
        return

    if data == "ss_port":
        await msg.edit_text("Port:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("443", callback_data="p_443")],
            [InlineKeyboardButton("8443", callback_data="p_8443")],
            [InlineKeyboardButton("2053", callback_data="p_2053")],
            [InlineKeyboardButton("2087", callback_data="p_2087")],
            [InlineKeyboardButton("Back", callback_data="set_server")],
        ]))
        return

    if data.startswith("p_"):
        port = data[2:]
        db.set_setting("xray_port", port)
        xray.reload_xray()
        await msg.edit_text(f"Port: {port}")

    if data == "ss_net":
        await msg.edit_text("Network:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("xhttp", callback_data="n_xhttp"),
             InlineKeyboardButton("grpc", callback_data="n_grpc")],
            [InlineKeyboardButton("websocket", callback_data="n_ws"),
             InlineKeyboardButton("tcp", callback_data="n_tcp")],
            [InlineKeyboardButton("Back", callback_data="set_server")],
        ]))
        return

    if data.startswith("n_"):
        net = data[2:]
        db.set_setting("xray_network", net)
        xray.reload_xray()
        await msg.edit_text(f"Network: {net}")

    if data == "ss_sec":
        await msg.edit_text("Security:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("none", callback_data="s_none"),
             InlineKeyboardButton("tls", callback_data="s_tls")],
            [InlineKeyboardButton("xtls", callback_data="s_xtls")],
            [InlineKeyboardButton("Back", callback_data="set_server")],
        ]))
        return

    if data.startswith("s_"):
        sec = data[2:]
        db.set_setting("xray_security", sec)
        xray.reload_xray()
        await msg.edit_text(f"Security: {sec}")

    if data == "ss_mode":
        await msg.edit_text("Mode:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("packet-up", callback_data="m_pktup"),
             InlineKeyboardButton("xudp", callback_data="m_xudp")],
            [InlineKeyboardButton("header", callback_data="m_header"),
             InlineKeyboardButton("gun", callback_data="m_gun")],
            [InlineKeyboardButton("Back", callback_data="set_server")],
        ]))
        return

    if data.startswith("m_"):
        mode_map = {"pktup": "packet-up", "xudp": "xudp", "header": "header", "gun": "gun"}
        mode = mode_map.get(data[2:], "packet-up")
        db.set_setting("xray_mode", mode)
        xray.reload_xray()
        await msg.edit_text(f"Mode: {mode}")

    # --- Backup/Restore ---
    if data == "set_backup":
        await msg.edit_text("Backup & Restore", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Backup Config", callback_data="backup_config")],
            [InlineKeyboardButton("Export DB", callback_data="export_db")],
            [InlineKeyboardButton("Back", callback_data="settings")],
        ]))
        return

    if data == "backup_config":
        try:
            import shutil
            shutil.copy2("/etc/xray/g2ray.json", "/tmp/xray_backup.json")
            await msg.edit_text("Backup saved: /tmp/xray_backup.json")
        except Exception as e:
            await msg.edit_text(f"Error: {e}")
        return

    if data == "export_db":
        src = str(db.DB_PATH)
        dst = "/tmp/buugereydy_backup.db"
        import shutil
        shutil.copy2(src, dst)
        await msg.edit_text(f"DB exported: {dst}")
        return

    # --- Server Stats ---
    if data == "server_stats":
        running = xray.check_xray_running()
        config = xray.generate_config()
        inbounds = config.get("inbounds", [])
        links = xray.get_all_links()
        text = (f"Server Stats\n\n"
                f"Xray: {'Running' if running else 'Stopped'}\n"
                f"Users: {len(links)}\n"
                f"Config: /etc/xray/g2ray.json\n\n"
                f"Inbounds: {len(inbounds)}\n"
                f"Port: {db.get_setting('xray_port') or '443'}\n"
                f"Network: {db.get_setting('xray_network') or 'xhttp'}\n"
                f"Security: {db.get_setting('xray_security') or 'none'}")
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Reload", callback_data="reload_config"),
             InlineKeyboardButton("Restart", callback_data="restart_xray")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]))
        return

    if data == "restart_xray":
        xray.reload_xray()
        await msg.edit_text("Xray restarted!")
    elif data == "stop_xray":
        xray.stop_xray()
        await msg.edit_text("Xray stopped.")
    elif data == "start_xray":
        xray.start_xray()
        await msg.edit_text("Xray started!")

    if data == "set_admin":
        await msg.edit_text(f"Add admin TG ID (numeric):\nCurrent: {', '.join(str(a) for a in db.get_admin_tg_ids())}")
        return

    # === TEXT INPUT HANDLERS ===

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("_au_step")
    tg_id = update.effective_user.id

    # --- Add User text flow ---
    if step == "au_lc":
        try:
            mb = int(text)
            context.user_data["_au_limit"] = mb
            context.user_data["_au_step"] = "expiry"
            await update.message.reply_text(f"Limit: {fmt_mb(mb)}\n\nSet expiry:")
        except ValueError:
            await update.message.reply_text("Valid number in MB:")
        return

    if step == "au_ec":
        context.user_data["_au_expiry"] = text
        context.user_data["_au_step"] = "chain"
        await update.message.reply_text(f"Expiry: {text}\n\nSet chain proxy (or leave empty):")
        return

    if step == "chain":
        context.user_data["_au_chain"] = text
        email = context.user_data.get("_au_email", "user_" + str(uuid.uuid4())[:4])
        limit = context.user_data.get("_au_limit", 0)
        expiry = context.user_data.get("_au_expiry")
        chain = text
        new_uuid = str(uuid.uuid4())
        db.add_user(new_uuid, email, limit, expiry, chain)
        xray.reload_xray()
        link = config_link(email, new_uuid)
        await update.message.reply_text(
            f"Created: {email}\n"
            f"UUID: {new_uuid}\n"
            f"Limit: {fmt_mb(limit)}\n"
            f"Expiry: {expiry or 'Never'}\n"
            f"Chain: {chain}\n\n"
            f"Link: {link[:100]}...")
        context.user_data.clear()
        return

    if step == "edit_limit_custom":
        email = context.user_data.get("_edit_email")
        try:
            mb = int(text)
            db.update_user_by_email(email, data_limit_mb=mb)
            xray.reload_xray()
            await update.message.reply_text(f"Limit set: {fmt_mb(mb)} for {email}")
        except ValueError:
            await update.message.reply_text("Valid MB number:")
        return

    if step == "edit_exp_custom":
        email = context.user_data.get("_edit_email")
        db.update_user_by_email(email, expiry_date=text)
        xray.reload_xray()
        await update.message.reply_text(f"Expiry set: {text} for {email}")
        return

    # --- Blacklist text ---
    bl_type = context.user_data.get("_bl_type")
    if bl_type == "domain":
        if text.lower() == "back":
            context.user_data.pop("_bl_type")
            await update.message.reply_text("Back to blacklist.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.add_blacklist("domain", text, source="tg:" + str(tg_id))
        await update.message.reply_text(f"Domain blacklisted: {text}")
        return

    if bl_type == "ip":
        if text.lower() == "back":
            context.user_data.pop("_bl_type")
            await update.message.reply_text("Back to blacklist.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.add_blacklist("ip", text, source="tg:" + str(tg_id))
        await update.message.reply_text(f"IP blacklisted: {text}")
        return

    # --- Chain proxy text ---
    chain_type = context.user_data.get("_chain_type")
    if chain_type == "http":
        if text.lower() == "back":
            context.user_data.pop("_chain_type")
            await update.message.reply_text("Back to chain settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("chain_proxy", text)
        xray.reload_xray()
        await update.message.reply_text(f"HTTP chain: {text}")
        return

    if chain_type == "socks":
        if text.lower() == "back":
            context.user_data.pop("_chain_type")
            await update.message.reply_text("Back to chain settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("chain_proxy", text)
        xray.reload_xray()
        await update.message.reply_text(f"SOCKS chain: {text}")
        return

    # --- DNS custom text ---
    dns_type = context.user_data.get("_dns_type")
    if dns_type == "custom":
        if text.lower() == "back":
            context.user_data.pop("_dns_type")
            await update.message.reply_text("Back to DNS settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("dns_server", text)
        xray.reload_xray()
        await update.message.reply_text(f"DNS: {text}")
        return

    # --- Admin add text ---
    try:
        new_id = int(text)
        admins = db.get_admin_tg_ids()
        if new_id not in admins:
            admins.append(new_id)
            db.set_setting("admin_tg_ids", ",".join(str(a) for a in admins))
            await update.message.reply_text(f"Admin added: {new_id}")
        else:
            await update.message.reply_text("Already admin.")
    except ValueError:
        await update.message.reply_text("Numeric ID only:")

# === COMMANDS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    admins = db.get_admin_tg_ids()
    if tg_id not in admins:
        admins.append(tg_id)
        db.set_setting("admin_tg_ids", ",".join(str(a) for a in admins))
    await update.message.reply_text(
        "Buugereydy VPN Manager v2.0\n\n"
        "Full Telegram management for your Xray server.\n\n"
        "Tap buttons below or use /menu.",
        reply_markup=main_markup())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Main menu:", reply_markup=main_markup())

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start bot\n"
        "/menu - Main menu\n"
        "/add - Quick add user\n"
        "/analytics - Quick analytics\n"
        "/stats - Server stats\n")

async def add_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["_au_step"] = "email"
    await update.message.reply_text("Enter email/name for new user:")

# === CODESPACE KEEPALIVE ===

async def keepalive_loop(application):
    """Pings GitHub to prevent 4-hour Codespace timeout."""
    import aiohttp
    print("[keepalive] Starting keepalive (every 10 min)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get("https://github.com", timeout=5) as resp:
                    if resp.status == 200:
                        print(f"[keepalive] OK at {datetime.now().strftime('%H:%M')}")
            except Exception as e:
                print(f"[keepalive] Fail: {e}")
            await asyncio.sleep(600)  # 10 minutes

# === MAIN ===

def main():
    db.init_db()
    print(f"[buugereydy] Bot starting... Config: {xray.CONFIG_PATH}")
    print(f"[buugereydy] Xray: {xray.XRAY_BIN}")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("add", add_quick))

    # Stats shortcut
    async def stats(update, context):
        await update.message.reply_text("Server Stats:", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("View", callback_data="server_stats")
        ]]))
    app.add_handler(CommandHandler("stats", stats))

    # Analytics shortcut
    async def analytics(update, context):
        await update.message.reply_text("Analytics:", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("View", callback_data="analytics")
        ]]))
    app.add_handler(CommandHandler("analytics", analytics))

    app.add_handler(CallbackQueryHandler(callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Run keepalive in background
    asyncio.create_task(keepalive_loop(app))

    # Start Xray if not running
    if not xray.check_xray_running():
        print("[buugereydy] Starting Xray...")
        xray.start_xray()

    print("[buugereydy] Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
