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

TOKEN = "8952649145:AAHEpUYHXkiaOzaVXhagMwvuqs8b9-rvQQY"

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

def config_link(email, uuid_val, config=None):
    if not config:
        config = xray.generate_config()
    info = xray.get_link_info(config)
    if not info:
        return "Link unavailable"
    return (
        f"vless://{uuid_val}@94.130.50.12:{info['port']}?"
        f"encryption=none&security=tls&sni={info['sni']}"
        f"&host={info['host']}&fp=chrome&allowInsecure=1"
        f"&type={info['network']}&mode={info['mode']}&path=%2F#{email}"
    )

def generate_qr(link):
    import qrcode
    qr = qrcode.make(link)
    path = Path(f"/tmp/qr_{uuid.uuid4().hex[:8]}.png")
    qr.save(str(path))
    return path

# === MARKUP BUILDERS ===

def main_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add User", callback_data="add_user"),
         InlineKeyboardButton("All Users", callback_data="all_users")],
        [InlineKeyboardButton("User Analytics", callback_data="analytics")],
        [InlineKeyboardButton("Config Mgmt", callback_data="config_mgmt")],
        [InlineKeyboardButton("Blacklist", callback_data="blacklist"),
         InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("Server Stats", callback_data="server_stats"),
         InlineKeyboardButton("Online Users", callback_data="online_users")],
        [InlineKeyboardButton("Notifications", callback_data="notifications")],
        [InlineKeyboardButton("Help", callback_data="help_menu")],
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
        [InlineKeyboardButton("View QR", callback_data=f"view_qr:{email}")],
        [InlineKeyboardButton("Traffic History", callback_data=f"traffic:{email}")],
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

def analytics_markup(days):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("7 Days", callback_data="analytics:7")],
        [InlineKeyboardButton("30 Days", callback_data="analytics:30")],
        [InlineKeyboardButton("90 Days", callback_data="analytics:90")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ])

def user_list_markup(users):
    kb = []
    for u in users[:30]:
        kb.append([InlineKeyboardButton(u["email"], callback_data=f"user_detail:{u['email']}")])
    kb.append([InlineKeyboardButton("Back", callback_data="back")])
    return InlineKeyboardMarkup(kb)

def traffic_history_markup(email):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Days", callback_data=f"traffic:{email}:30")],
        [InlineKeyboardButton("90 Days", callback_data=f"traffic:{email}:90")],
        [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
    ])

def server_stats_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Refresh", callback_data="server_stats")],
        [InlineKeyboardButton("System Info", callback_data="sys_info")],
        [InlineKeyboardButton("Network", callback_data="net_stats")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ])

def batch_user_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Data Limit", callback_data="batch_limit")],
        [InlineKeyboardButton("Set Expiry", callback_data="batch_expiry")],
        [InlineKeyboardButton("Enable All", callback_data="batch_enable")],
        [InlineKeyboardButton("Disable All", callback_data="batch_disable")],
        [InlineKeyboardButton("Blacklist All", callback_data="batch_blacklist")],
        [InlineKeyboardButton("Reset All Data", callback_data="batch_reset")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ])

def backup_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Backup Config", callback_data="backup_config")],
        [InlineKeyboardButton("Restore Config", callback_data="restore_config")],
        [InlineKeyboardButton("Export DB", callback_data="export_db")],
        [InlineKeyboardButton("Import DB", callback_data="import_db")],
        [InlineKeyboardButton("Backup All Users", callback_data="backup_users")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ])

# === TEXT HELPERS ===

def user_detail_text(user):
    limit_str = fmt_mb(user["data_limit_mb"]) if user["data_limit_mb"] else "Unlimited"
    pct = ""
    if user["data_limit_mb"] and user["data_limit_mb"] > 0:
        pct = f"\nData Usage: {fmt_mb(user['data_used_mb'])} / {limit_str} ({user['data_used_mb']/max(user['data_limit_mb'],1)*100:.0f}%)"
    return (
        f"User: {user['email']}\n\n"
        f"UUID: {user['uuid']}\n"
        f"Enabled: {'Yes' if user['enabled'] else 'No'}\n"
        f"Blacklisted: {'Yes' if user['blacklist'] else 'No'}"
        f"{pct}\n"
        f"Data Limit: {limit_str}\n"
        f"Data Used: {fmt_mb(user['data_used_mb'])}\n"
        f"Expiry: {user.get('expiry_date') or 'No expiry'}\n"
        f"Created: {fmt_time(user['created_at'])}\n"
        f"Chain Proxy: {user.get('chain_proxy') or 'None'}"
    )

# === CALLBACK HANDLERS (each page = separate handler) ===

async def callback_back(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Main menu:", reply_markup=main_markup())

async def callback_add_user(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Create new user\n\n"
        "1. Set data limit\n"
        "2. Set expiry date\n"
        "3. Set chain proxy\n"
        "4. Done - generates config",
        reply_markup=add_user_markup())

async def callback_add_user_limit(update, context):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        *[InlineKeyboardButton(f"{p}GB", callback_data=f"au_lp:{p*1024}") for p in [1,3,5,10,20,50,100]],
        [InlineKeyboardButton("Custom (MB)", callback_data="au_lc")],
        [InlineKeyboardButton("Unlimited", callback_data="au_ln")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("Data limit (MB)\n\nSelect preset or enter custom:", reply_markup=kb)

async def callback_add_user_limit_preset(update, context):
    query = update.callback_query
    await query.answer()
    mb = int(query.data.split(":")[1])
    context.user_data["_au_limit"] = mb
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Day", callback_data="au_ep:1d"),
         InlineKeyboardButton("3 Days", callback_data="au_ep:3d")],
        [InlineKeyboardButton("1 Week", callback_data="au_ep:1w"),
         InlineKeyboardButton("2 Weeks", callback_data="au_ep:2w")],
        [InlineKeyboardButton("1 Month", callback_data="au_ep:1m"),
         InlineKeyboardButton("3 Months", callback_data="au_ep:3m")],
        [InlineKeyboardButton("6 Months", callback_data="au_ep:6m"),
         InlineKeyboardButton("1 Year", callback_data="au_ep:1y")],
        [InlineKeyboardButton("Custom", callback_data="au_ec")],
        [InlineKeyboardButton("None", callback_data="au_en")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text(f"Limit: {fmt_mb(mb)}\n\nSelect expiry:", reply_markup=kb)

async def callback_add_user_limit_custom(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_au_step"] = "au_lc"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("Enter custom limit in MB:", reply_markup=kb)

async def callback_add_user_limit_none(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_au_limit"] = 0
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Day", callback_data="au_ep:1d"),
         InlineKeyboardButton("3 Days", callback_data="au_ep:3d")],
        [InlineKeyboardButton("1 Week", callback_data="au_ep:1w"),
         InlineKeyboardButton("2 Weeks", callback_data="au_ep:2w")],
        [InlineKeyboardButton("1 Month", callback_data="au_ep:1m"),
         InlineKeyboardButton("3 Months", callback_data="au_ep:3m")],
        [InlineKeyboardButton("6 Months", callback_data="au_ep:6m"),
         InlineKeyboardButton("1 Year", callback_data="au_ep:1y")],
        [InlineKeyboardButton("Custom", callback_data="au_ec")],
        [InlineKeyboardButton("None", callback_data="au_en")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("Unlimited.\n\nSelect expiry:", reply_markup=kb)

async def callback_add_user_expiry(update, context):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Day", callback_data="au_ep:1d"),
         InlineKeyboardButton("3 Days", callback_data="au_ep:3d")],
        [InlineKeyboardButton("1 Week", callback_data="au_ep:1w"),
         InlineKeyboardButton("2 Weeks", callback_data="au_ep:2w")],
        [InlineKeyboardButton("1 Month", callback_data="au_ep:1m"),
         InlineKeyboardButton("3 Months", callback_data="au_ep:3m")],
        [InlineKeyboardButton("6 Months", callback_data="au_ep:6m"),
         InlineKeyboardButton("1 Year", callback_data="au_ep:1y")],
        [InlineKeyboardButton("Custom", callback_data="au_ec")],
        [InlineKeyboardButton("None", callback_data="au_en")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("Expiry date\n\nSelect duration:", reply_markup=kb)

async def callback_add_user_expiry_preset(update, context):
    query = update.callback_query
    await query.answer()
    dur = query.data.split(":")[1]
    context.user_data["_au_expiry"] = calculate_expiry(dur)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Chain Proxy", callback_data="au_chain")],
        [InlineKeyboardButton("Done & Create", callback_data="au_done")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text(f"Expiry: {context.user_data['_au_expiry']}\n\nSet chain or tap Done:", reply_markup=kb)

async def callback_add_user_expiry_custom(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_au_step"] = "au_ec"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("Enter date (YYYY-MM-DD):", reply_markup=kb)

async def callback_add_user_expiry_none(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_au_expiry"] = None
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Chain Proxy", callback_data="au_chain")],
        [InlineKeyboardButton("Done & Create", callback_data="au_done")],
        [InlineKeyboardButton("Back", callback_data="add_user")],
    ])
    await query.message.edit_text("No expiry.\n\nSet chain or tap Done:", reply_markup=kb)

async def callback_add_user_chain(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_au_step"] = "chain"
    await query.message.edit_text(
        "Chain proxy for this user:\n\n"
        "Format: http://user:pass@host:port\n"
        "Or: socks://host:port\n\nEmpty = direct.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="add_user")]]))

async def callback_add_user_done(update, context):
    query = update.callback_query
    await query.answer()
    email = context.user_data.get("_au_email", "user_" + str(uuid.uuid4())[:8])
    limit = context.user_data.get("_au_limit", 0)
    expiry = context.user_data.get("_au_expiry")
    chain = context.user_data.get("_au_chain", "")
    new_uuid = str(uuid.uuid4())
    db.add_user(new_uuid, email, limit, expiry, chain)
    xray.reload_xray()
    link = config_link(email, new_uuid)
    await query.message.edit_text(
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

async def callback_all_users(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    if not users:
        await query.message.edit_text("No users yet.")
        return
    total = len(users)
    enabled = sum(1 for u in users if u["enabled"])
    expired = sum(1 for u in users if u.get("expiry_date") and datetime.strptime(u["expiry_date"], "%Y-%m-%d") < datetime.now())
    limited = sum(1 for u in users if u["data_limit_mb"] > 0)
    text = (f"All Users ({total})\nEnabled: {enabled} | Expired: {expired} | Limited: {limited}\n\n"
            f"Tap a user:")
    await query.message.edit_text(text, reply_markup=user_list_markup(users))

async def callback_user_detail(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    user = db.get_user_by_email(email)
    if not user:
        await query.message.edit_text("User not found.")
        return
    await query.message.edit_text(user_detail_text(user), reply_markup=user_detail_markup(email))

async def callback_edit_limit(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    user = db.get_user_by_email(email)
    kb = InlineKeyboardMarkup([
        *[InlineKeyboardButton(f"{p}GB", callback_data=f"limit_set:{email}:{p*1024}") for p in [1,3,5,10,20,50,100]],
        [InlineKeyboardButton("Custom (MB)", callback_data=f"limit_custom:{email}")],
        [InlineKeyboardButton("Unlimited", callback_data=f"limit_unset:{email}")],
        [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
    ])
    cur = fmt_mb(user["data_limit_mb"]) if user["data_limit_mb"] else "Unlimited"
    await query.message.edit_text(f"Limit for {email}\nCurrent: {cur}\nUsed: {fmt_mb(user['data_used_mb'])}\n\nSelect:", reply_markup=kb)

async def callback_limit_set(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    db.update_user_by_email(parts[1], data_limit_mb=int(parts[2]))
    xray.reload_xray()
    await query.message.edit_text(f"Limit set: {fmt_mb(int(parts[2]))} for {parts[1]}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{parts[1]}")]]))

async def callback_limit_custom(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    context.user_data["_edit_email"] = email
    context.user_data["_au_step"] = "edit_limit_custom"
    await query.message.edit_text(f"Enter limit in MB for {email}:")

async def callback_limit_unset(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    db.update_user_by_email(email, data_limit_mb=0)
    xray.reload_xray()
    await query.message.edit_text(f"Unlimited for {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_edit_expiry(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Day", callback_data=f"exp_set:{email}:1d")],
        [InlineKeyboardButton("3 Days", callback_data=f"exp_set:{email}:3d")],
        [InlineKeyboardButton("1 Week", callback_data=f"exp_set:{email}:1w")],
        [InlineKeyboardButton("2 Weeks", callback_data=f"exp_set:{email}:2w")],
        [InlineKeyboardButton("1 Month", callback_data=f"exp_set:{email}:1m")],
        [InlineKeyboardButton("3 Months", callback_data=f"exp_set:{email}:3m")],
        [InlineKeyboardButton("6 Months", callback_data=f"exp_set:{email}:6m")],
        [InlineKeyboardButton("1 Year", callback_data=f"exp_set:{email}:1y")],
        [InlineKeyboardButton("Custom", callback_data=f"exp_custom:{email}")],
        [InlineKeyboardButton("Remove", callback_data=f"exp_unset:{email}")],
        [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
    ])
    await query.message.edit_text(f"Expiry for {email}\nCurrent: {db.get_user_by_email(email).get('expiry_date') or 'No expiry'}\n\nSelect:", reply_markup=kb)

async def callback_expiry_set(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    expiry = calculate_expiry(parts[2])
    db.update_user_by_email(parts[1], expiry_date=expiry)
    xray.reload_xray()
    await query.message.edit_text(f"Expiry set: {expiry} for {parts[1]}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{parts[1]}")]]))

async def callback_expiry_custom(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    context.user_data["_edit_email"] = email
    context.user_data["_au_step"] = "edit_exp_custom"
    await query.message.edit_text(f"Enter date (YYYY-MM-DD) for {email}:")

async def callback_expiry_unset(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    db.update_user_by_email(email, expiry_date=None)
    xray.reload_xray()
    await query.message.edit_text(f"Expiry removed for {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_toggle_block(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    u = db.get_user_by_email(email)
    db.update_user_by_email(email, blacklist=0 if u["blacklist"] else 1)
    xray.reload_xray()
    await query.message.edit_text(f"{'Blacklisted' if not u['blacklist'] else 'Unblocked'}: {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_reset_data(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    db.update_user_by_email(email, data_used_mb=0)
    await query.message.edit_text(f"Data reset: {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_toggle_enable(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    u = db.get_user_by_email(email)
    db.update_user_by_email(email, enabled=0 if u["enabled"] else 1)
    xray.reload_xray()
    await query.message.edit_text(f"{'Enabled' if not u['enabled'] else 'Disabled'}: {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_view_link(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    u = db.get_user_by_email(email)
    if not u:
        await query.message.edit_text("User not found.")
        return
    link = config_link(email, u["uuid"])
    await query.message.edit_text(f"Config for {email}:\n\n{link}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_view_qr(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    u = db.get_user_by_email(email)
    if not u:
        await query.message.edit_text("User not found.")
        return
    link = config_link(email, u["uuid"])
    qr_path = generate_qr(link)
    await query.message.reply_photo(photo=open(qr_path, "rb"),
        caption=f"QR for {email}\n\n{link[:100]}...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))

async def callback_traffic(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    email = parts[1]
    days = int(parts[2]) if len(parts) > 2 else 30
    summary = db.get_traffic_summary(days)
    user_data = db.get_user_by_email(email)
    if not user_data:
        await query.message.edit_text("User not found.")
        return
    user_traffic = next((t for t in summary if t["email"] == email), None)
    total_used = fmt_mb(user_traffic["total_used"]) if user_traffic else "No data"
    snapshots = user_traffic["snapshots"] if user_traffic else 0
    limit_str = fmt_mb(user_data["data_limit_mb"]) if user_data["data_limit_mb"] else "Unlimited"
    usage_pct = ""
    if user_data["data_limit_mb"] and user_data["data_limit_mb"] > 0:
        usage_pct = f"\nUsage: {total_used} / {limit_str} ({total_used.replace(' GB','').replace(' MB','')}/{limit_str.replace(' GB','').replace(' MB','')})"
    text = (f"Traffic - {email}\n\n"
            f"Period: {days} days\n"
            f"Data Used: {total_used}\n"
            f"Data Limit: {limit_str}\n"
            f"Snapshots: {snapshots}")
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Days", callback_data=f"traffic:{email}:30")],
        [InlineKeyboardButton("90 Days", callback_data=f"traffic:{email}:90")],
        [InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")],
    ]))

async def callback_del_user(update, context):
    query = update.callback_query
    await query.answer()
    email = query.data.split(":")[1]
    db.delete_user_by_email(email)
    xray.reload_xray()
    await query.message.edit_text(f"Deleted: {email}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("All Users", callback_data="all_users")]]))

async def callback_analytics(update, context):
    query = update.callback_query
    await query.answer()
    days = 7
    if ":" in query.data:
        days = int(query.data.split(":")[1])
    users = db.get_all_users()
    if not users:
        await query.message.edit_text("No users.")
        return
    total = len(users)
    enabled = sum(1 for u in users if u["enabled"])
    expired = sum(1 for u in users if u.get("expiry_date") and datetime.strptime(u["expiry_date"], "%Y-%m-%d") < datetime.now())
    limited = sum(1 for u in users if u["data_limit_mb"] > 0)
    total_used = sum(u["data_used_mb"] for u in users)
    top = sorted(users, key=lambda u: u["data_used_mb"], reverse=True)[:5]
    text = (f"Analytics ({days} days)\n\n"
            f"Total Users: {total}\n"
            f"Active: {enabled} | Expired: {expired}\n"
            f"Data Limited: {limited}\n"
            f"Total Data Used: {fmt_mb(total_used)}\n")
    if top:
        text += "\nTop Consumers:\n"
        for i, u in enumerate(top, 1):
            pct = ""
            if u["data_limit_mb"] and u["data_limit_mb"] > 0:
                pct = f" ({u['data_used_mb']/u['data_limit_mb']*100:.0f}%)"
            text += f"{i}. {u['email']}: {fmt_mb(u['data_used_mb'])}{pct}\n"
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("All Users", callback_data="all_users"),
         InlineKeyboardButton("Export CSV", callback_data="export_csv")],
        [InlineKeyboardButton("Batch Ops", callback_data="batch_ops")],
        [InlineKeyboardButton("7 Days", callback_data="analytics:7"),
         InlineKeyboardButton("30 Days", callback_data="analytics:30"),
         InlineKeyboardButton("90 Days", callback_data="analytics:90")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ]))

async def callback_export_csv(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    csv = "Email,UUID,Limit(MB),Used(MB),Expiry,Enabled,Blacklist\n"
    for u in users:
        csv += f"{u['email']},{u['uuid']},{u['data_limit_mb']},{u['data_used_mb']},{u['expiry_date'] or ''},{u['enabled']},{u['blacklist']}\n"
    Path("/tmp/users.csv").write_text(csv)
    await query.message.reply_document(document=open("/tmp/users.csv", "rb"),
        filename="users_export.csv",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="analytics")]]))

async def callback_batch_ops(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    text = f"Batch Operations ({len(users)} users)\n\nSelect action:"
    await query.message.edit_text(text, reply_markup=batch_user_markup())

async def callback_batch_limit(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_batch_step"] = "limit"
    kb = InlineKeyboardMarkup([
        *[InlineKeyboardButton(f"{p}GB", callback_data=f"bl:{p*1024}") for p in [1,3,5,10,20,50]],
        [InlineKeyboardButton("Custom (MB)", callback_data="bl_custom")],
        [InlineKeyboardButton("Back", callback_data="batch_ops")],
    ])
    await query.message.edit_text("Set data limit for ALL limited users\n\nSelect preset:", reply_markup=kb)

async def callback_batch_limit_preset(update, context):
    query = update.callback_query
    await query.answer()
    mb = int(query.data.split(":")[1])
    users = db.get_limit_users()
    for u in users:
        db.update_user_by_email(u["email"], data_limit_mb=mb)
    xray.reload_xray()
    await query.message.edit_text(f"Set {fmt_mb(mb)} for {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_batch_limit_custom(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_batch_step"] = "bl_custom"
    await query.message.edit_text("Enter custom limit in MB for all limited users:")

async def callback_batch_expiry(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_batch_step"] = "expiry"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month", callback_data="be:1m")],
        [InlineKeyboardButton("3 Months", callback_data="be:3m")],
        [InlineKeyboardButton("6 Months", callback_data="be:6m")],
        [InlineKeyboardButton("1 Year", callback_data="be:1y")],
        [InlineKeyboardButton("Custom", callback_data="be_custom")],
        [InlineKeyboardButton("Back", callback_data="batch_ops")],
    ])
    await query.message.edit_text("Set expiry for ALL users\n\nSelect:", reply_markup=kb)

async def callback_batch_expiry_preset(update, context):
    query = update.callback_query
    await query.answer()
    dur = query.data.split(":")[1]
    expiry = calculate_expiry(dur)
    users = db.get_all_users()
    for u in users:
        db.update_user_by_email(u["email"], expiry_date=expiry)
    xray.reload_xray()
    await query.message.edit_text(f"Expiry set to {expiry} for {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_batch_expiry_custom(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_batch_step"] = "be_custom"
    await query.message.edit_text("Enter date (YYYY-MM-DD) for all users:")

async def callback_batch_enable(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    for u in users:
        db.update_user_by_email(u["email"], enabled=1)
    xray.reload_xray()
    await query.message.edit_text(f"Enabled {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_batch_disable(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    for u in users:
        db.update_user_by_email(u["email"], enabled=0)
    xray.reload_xray()
    await query.message.edit_text(f"Disabled {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_batch_blacklist(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    for u in users:
        db.update_user_by_email(u["email"], blacklist=1)
    xray.reload_xray()
    await query.message.edit_text(f"Blacklisted {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_batch_reset(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    for u in users:
        db.update_user_by_email(u["email"], data_used_mb=0)
    await query.message.edit_text(f"Reset data for {len(users)} users",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))

async def callback_config_mgmt(update, context):
    query = update.callback_query
    await query.answer()
    links = xray.get_all_links()
    config = xray.generate_config()
    text = (f"Config Management\n\n"
            f"Users: {len(links)}\n"
            f"Config: /etc/xray/g2ray.json\n"
            f"Xray Running: {'Yes' if xray.check_xray_running() else 'No'}\n\n"
            f"Actions:")
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Generate Links", callback_data="gen_links")],
        [InlineKeyboardButton("All Users", callback_data="all_users")],
        [InlineKeyboardButton("Export JSON", callback_data="export_config")],
        [InlineKeyboardButton("Reload Config", callback_data="reload_config")],
        [InlineKeyboardButton("Backup/Restore", callback_data="set_backup")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ]))

async def callback_gen_links(update, context):
    query = update.callback_query
    await query.answer()
    links = xray.get_all_links()
    if not links:
        await query.message.edit_text("No links.")
        return
    text = f"Links ({len(links)})\n\n"
    for l in links[:5]:
        text += f"{l['email']}: {l['link'][:80]}...\n"
    if len(links) > 5:
        text += f"\n... +{len(links)-5} more"
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("All Links", callback_data="all_links")],
        [InlineKeyboardButton("Back", callback_data="config_mgmt")],
    ]))

async def callback_all_links(update, context):
    query = update.callback_query
    await query.answer()
    links = xray.get_all_links()
    if not links:
        await query.message.edit_text("No links.")
        return
    for l in links:
        await query.message.reply_text(f"{l['email']}:\n{l['link']}")
    await query.message.edit_text("Links sent.")

async def callback_export_config(update, context):
    query = update.callback_query
    await query.answer()
    config = xray.generate_config()
    Path("/tmp/config.json").write_text(json.dumps(config, indent=2))
    await query.message.reply_document(document=open("/tmp/config.json", "rb"),
        filename="xray_config.json",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="config_mgmt")]]))

async def callback_reload_config(update, context):
    query = update.callback_query
    await query.answer()
    xray.reload_xray()
    await query.message.edit_text("Reloaded!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="config_mgmt")]]))

async def callback_blacklist(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Blacklist", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Domain Blacklist", callback_data="bl_domains")],
        [InlineKeyboardButton("IP Blacklist", callback_data="bl_ips")],
        [InlineKeyboardButton("Blacklisted Users", callback_data="bl_users")],
        [InlineKeyboardButton("Back", callback_data="back")],
    ]))

async def callback_bl_domains(update, context):
    query = update.callback_query
    await query.answer()
    domains = db.get_blacklist("domain")
    text = f"Domain Blacklist ({len(domains)})\n\n"
    text += "\n".join(f"- {d['value']}" for d in domains[:50]) if domains else "Empty."
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Add", callback_data="bl_add_domain")],
        [InlineKeyboardButton("Back", callback_data="blacklist")],
    ]))

async def callback_bl_add_domain(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_bl_type"] = "domain"
    await query.message.edit_text("Enter domain to blacklist (e.g. google.com):\nType 'back' to return.")

async def callback_bl_ips(update, context):
    query = update.callback_query
    await query.answer()
    ips = db.get_blacklist("ip")
    text = f"IP Blacklist ({len(ips)})\n\n"
    text += "\n".join(f"- {i['value']}" for i in ips[:50]) if ips else "Empty."
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Add", callback_data="bl_add_ip")],
        [InlineKeyboardButton("Back", callback_data="blacklist")],
    ]))

async def callback_bl_add_ip(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_bl_type"] = "ip"
    await query.message.edit_text("Enter IP/range (e.g. 1.1.1.1):\nType 'back' to return.")

async def callback_bl_users(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    bl = [u for u in users if u["blacklist"]]
    text = f"Blacklisted Users ({len(bl)})\n\n"
    text += "\n".join(f"- {u['email']}" for u in bl[:50]) if bl else "None."
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="blacklist")]]))

async def callback_settings(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Settings", reply_markup=settings_markup())

async def callback_set_chain(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Chain Proxy", reply_markup=chain_markup())

async def callback_chain_current(update, context):
    query = update.callback_query
    await query.answer()
    chain = db.get_setting("chain_proxy")
    await query.message.edit_text(f"Current: {chain or 'None'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_chain")]]))

async def callback_chain_http(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_chain_type"] = "http"
    await query.message.edit_text("HTTP proxy:\nhttp://user:pass@host:port\nType 'back' to return.")

async def callback_chain_socks(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_chain_type"] = "socks"
    await query.message.edit_text("SOCKS5 proxy:\nsocks://host:port\nType 'back' to return.")

async def callback_chain_remove(update, context):
    query = update.callback_query
    await query.answer()
    db.set_setting("chain_proxy", "")
    xray.reload_xray()
    await query.message.edit_text("Chain removed.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_chain")]]))

async def callback_set_dns(update, context):
    query = update.callback_query
    await query.answer()
    current = db.get_setting("dns_server") or "https://1.1.1.1/dns-query"
    await query.message.edit_text(f"Current DNS: {current}\n\nSelect:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Cloudflare", callback_data="dns_cf")],
        [InlineKeyboardButton("Google", callback_data="dns_google")],
        [InlineKeyboardButton("Quad9", callback_data="dns_quad9")],
        [InlineKeyboardButton("Custom", callback_data="dns_custom")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ]))

async def callback_dns_cf(update, context):
    query = update.callback_query
    await query.answer()
    db.set_setting("dns_server", "https://1.1.1.1/dns-query")
    xray.reload_xray()
    await query.message.edit_text("DNS: Cloudflare",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_dns")]]))

async def callback_dns_google(update, context):
    query = update.callback_query
    await query.answer()
    db.set_setting("dns_server", "https://dns.google/dns-query")
    xray.reload_xray()
    await query.message.edit_text("DNS: Google",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_dns")]]))

async def callback_dns_quad9(update, context):
    query = update.callback_query
    await query.answer()
    db.set_setting("dns_server", "https://dns.quad9.net/dns-query")
    xray.reload_xray()
    await query.message.edit_text("DNS: Quad9",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_dns")]]))

async def callback_dns_custom(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_dns_type"] = "custom"
    await query.message.edit_text("Custom DNS URL:\nType 'back' to return.")

async def callback_set_domain_bl(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Domain Blacklist", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Add", callback_data="bl_add_domain")],
        [InlineKeyboardButton("View All", callback_data="bl_domains")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ]))

async def callback_set_routing(update, context):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'OFF' if db.get_setting('bittorrent_block')=='0' else 'ON'} Bittorrent", callback_data="route_bt"),
         InlineKeyboardButton(f"{'OFF' if db.get_setting('ads_block')=='0' else 'ON'} Ads", callback_data="route_ads")],
        [InlineKeyboardButton(f"{'OFF' if db.get_setting('private_ip_block')=='0' else 'ON'} Private IPs", callback_data="route_priv"),
         InlineKeyboardButton(f"{'OFF' if db.get_setting('sniffing_enabled')=='0' else 'ON'} Sniffing", callback_data="route_sniff")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ])
    await query.message.edit_text("Toggle routing rules:", reply_markup=kb)

async def callback_route_bt(update, context):
    query = update.callback_query
    await query.answer()
    cur = db.get_setting("bittorrent_block")
    db.set_setting("bittorrent_block", "0" if cur == "1" else "1")
    xray.reload_xray()
    await query.message.edit_text(f"BT block {'ON' if db.get_setting('bittorrent_block')=='1' else 'OFF'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_routing")]]))

async def callback_route_ads(update, context):
    query = update.callback_query
    await query.answer()
    cur = db.get_setting("ads_block")
    db.set_setting("ads_block", "0" if cur == "1" else "1")
    xray.reload_xray()
    await query.message.edit_text(f"Ads block {'ON' if db.get_setting('ads_block')=='1' else 'OFF'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_routing")]]))

async def callback_route_priv(update, context):
    query = update.callback_query
    await query.answer()
    cur = db.get_setting("private_ip_block")
    db.set_setting("private_ip_block", "0" if cur == "1" else "1")
    xray.reload_xray()
    await query.message.edit_text(f"Private IP block {'ON' if db.get_setting('private_ip_block')=='1' else 'OFF'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_routing")]]))

async def callback_route_sniff(update, context):
    query = update.callback_query
    await query.answer()
    cur = db.get_setting("sniffing_enabled")
    db.set_setting("sniffing_enabled", "0" if cur == "1" else "1")
    xray.reload_xray()
    await query.message.edit_text(f"Sniffing {'ON' if db.get_setting('sniffing_enabled')=='1' else 'OFF'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_routing")]]))

async def callback_set_server(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Server Settings", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Port: {db.get_setting('xray_port') or '443'}", callback_data="ss_port")],
        [InlineKeyboardButton(f"Network: {db.get_setting('xray_network') or 'xhttp'}", callback_data="ss_net")],
        [InlineKeyboardButton(f"Security: {db.get_setting('xray_security') or 'none'}", callback_data="ss_sec")],
        [InlineKeyboardButton(f"Mode: {db.get_setting('xray_mode') or 'packet-up'}", callback_data="ss_mode")],
        [InlineKeyboardButton("Restart Xray", callback_data="restart_xray"),
         InlineKeyboardButton("Stop", callback_data="stop_xray")],
        [InlineKeyboardButton("Start", callback_data="start_xray")],
        [InlineKeyboardButton("Back", callback_data="settings")],
    ]))

async def callback_ss_port(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Port:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("443", callback_data="p_443"),
         InlineKeyboardButton("8443", callback_data="p_8443")],
        [InlineKeyboardButton("2053", callback_data="p_2053"),
         InlineKeyboardButton("2087", callback_data="p_2087")],
        [InlineKeyboardButton("Back", callback_data="set_server")],
    ]))

async def callback_ss_port_set(update, context):
    query = update.callback_query
    await query.answer()
    port = query.data[2:]
    db.set_setting("xray_port", port)
    xray.reload_xray()
    await query.message.edit_text(f"Port: {port}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_ss_net(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Network:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("xhttp", callback_data="n_xhttp"),
         InlineKeyboardButton("grpc", callback_data="n_grpc")],
        [InlineKeyboardButton("websocket", callback_data="n_ws"),
         InlineKeyboardButton("tcp", callback_data="n_tcp")],
        [InlineKeyboardButton("Back", callback_data="set_server")],
    ]))

async def callback_ss_net_set(update, context):
    query = update.callback_query
    await query.answer()
    net = query.data[2:]
    db.set_setting("xray_network", net)
    xray.reload_xray()
    await query.message.edit_text(f"Network: {net}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_ss_sec(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Security:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("none", callback_data="s_none"),
         InlineKeyboardButton("tls", callback_data="s_tls")],
        [InlineKeyboardButton("xtls", callback_data="s_xtls")],
        [InlineKeyboardButton("Back", callback_data="set_server")],
    ]))

async def callback_ss_sec_set(update, context):
    query = update.callback_query
    await query.answer()
    sec = query.data[2:]
    db.set_setting("xray_security", sec)
    xray.reload_xray()
    await query.message.edit_text(f"Security: {sec}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_ss_mode(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Mode:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("packet-up", callback_data="m_pktup"),
         InlineKeyboardButton("xudp", callback_data="m_xudp")],
        [InlineKeyboardButton("header", callback_data="m_header"),
         InlineKeyboardButton("gun", callback_data="m_gun")],
        [InlineKeyboardButton("Back", callback_data="set_server")],
    ]))

async def callback_ss_mode_set(update, context):
    query = update.callback_query
    await query.answer()
    mode_map = {"pktup": "packet-up", "xudp": "xudp", "header": "header", "gun": "gun"}
    mode = mode_map.get(query.data[2:], "packet-up")
    db.set_setting("xray_mode", mode)
    xray.reload_xray()
    await query.message.edit_text(f"Mode: {mode}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_backup(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Backup & Restore", reply_markup=backup_markup())

async def callback_backup_config(update, context):
    query = update.callback_query
    await query.answer()
    try:
        import shutil
        shutil.copy2("/etc/xray/g2ray.json", "/tmp/xray_backup.json")
        await query.message.reply_document(document=open("/tmp/xray_backup.json", "rb"),
            filename="xray_backup.json",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_backup")]]))
    except Exception as e:
        await query.message.edit_text(f"Error: {e}")

async def callback_restore_config(update, context):
    query = update.callback_query
    await query.answer()
    try:
        import shutil
        shutil.copy2("/tmp/xray_backup.json", "/etc/xray/g2ray.json")
        xray.reload_xray()
        await query.message.edit_text("Config restored and reloaded!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_backup")]]))
    except Exception as e:
        await query.message.edit_text(f"Restore error: {e}")

async def callback_export_db(update, context):
    query = update.callback_query
    await query.answer()
    src = str(db.DB_PATH)
    dst = "/tmp/buugereydy_backup.db"
    import shutil
    shutil.copy2(src, dst)
    await query.message.reply_document(document=open(dst, "rb"),
        filename="buugereydy_backup.db",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_backup")]]))

async def callback_import_db(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["_import_step"] = True
    await query.message.edit_text("Send database file to restore.")

async def callback_backup_users(update, context):
    query = update.callback_query
    await query.answer()
    users = db.get_all_users()
    data = json.dumps(users, indent=2)
    Path("/tmp/users_backup.json").write_text(data)
    await query.message.reply_document(document=open("/tmp/users_backup.json", "rb"),
        filename="users_backup.json",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_backup")]]))

async def callback_server_stats(update, context):
    query = update.callback_query
    await query.answer()
    running = xray.check_xray_running()
    config = xray.generate_config()
    inbounds = config.get("inbounds", [])
    links = xray.get_all_links()
    traffic = xray.get_traffic_stats()
    online = len(db.get_online_users())
    text = (f"Server Stats\n\n"
            f"Xray: {'Running' if running else 'Stopped'}\n"
            f"Users: {len(links)}\n"
            f"Online: {online}\n"
            f"Config: /etc/xray/g2ray.json\n\n"
            f"Inbounds: {len(inbounds)}\n"
            f"Port: {db.get_setting('xray_port') or '443'}\n"
            f"Network: {db.get_setting('xray_network') or 'xhttp'}\n"
            f"Security: {db.get_setting('xray_security') or 'none'}\n\n"
            f"Traffic Stats ({len(traffic)} users with stats)")
    await query.message.edit_text(text, reply_markup=server_stats_markup())

async def callback_sys_info(update, context):
    query = update.callback_query
    await query.answer()
    stats = xray.get_system_stats()
    text = (f"System Info\n\n"
            f"CPU: {stats['cpu']}%\n"
            f"Memory: {stats['memory']}%\n"
            f"Disk: {stats['disk']}%\n"
            f"Net Sent: {fmt_bytes(stats['network_sent'])}\n"
            f"Net Recv: {fmt_bytes(stats['network_recv'])}")
    await query.message.edit_text(text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="server_stats")]]))

async def callback_net_stats(update, context):
    query = update.callback_query
    await query.answer()
    traffic = xray.get_traffic_stats()
    total_up = sum(t["up"] for t in traffic.values())
    total_down = sum(t["down"] for t in traffic.values())
    text = (f"Network Stats\n\n"
            f"Users with traffic: {len(traffic)}\n"
            f"Total Up: {fmt_bytes(total_up)}\n"
            f"Total Down: {fmt_bytes(total_down)}\n"
            f"Total: {fmt_bytes(total_up + total_down)}")
    await query.message.edit_text(text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="server_stats")]]))

async def callback_online_users(update, context):
    query = update.callback_query
    await query.answer()
    online = db.get_online_users()
    if not online:
        await query.message.edit_text("No online users.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
        return
    text = f"Online Users ({len(online)})\n\n"
    for u in online[:20]:
        elapsed = time.time() - u["connected_at"]
        mins = int(elapsed // 60)
        hours = int(mins // 60)
        if hours > 0:
            dur = f"{hours}h {mins%60}m"
        else:
            dur = f"{mins}m"
        text += f"{u['email']}: {dur}\n"
    if len(online) > 20:
        text += f"\n... +{len(online)-20} more"
    await query.message.edit_text(text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))

async def callback_notifications(update, context):
    query = update.callback_query
    await query.answer()
    tg_id = update.effective_user.id
    unread = db.get_unread_notifications(tg_id)
    if not unread:
        await query.message.edit_text("No notifications.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
        return
    text = f"Notifications ({len(unread)})\n\n"
    for n in unread[:20]:
        text += f"[{n['id']}] {n['message'][:60]}\n"
    kb = [[InlineKeyboardButton(f"Mark {n['id']}", callback_data=f"notif_read:{n['id']}")] for n in unread[:5]]
    kb.append([InlineKeyboardButton("Mark All Read", callback_data="notif_readall")])
    kb.append([InlineKeyboardButton("Back", callback_data="back")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def callback_notif_read(update, context):
    query = update.callback_query
    await query.answer()
    n_id = int(query.data.split(":")[1])
    db.mark_notification_read(update.effective_user.id, n_id)
    await query.message.edit_text(f"Notification {n_id} marked read.")

async def callback_notif_readall(update, context):
    query = update.callback_query
    await query.answer()
    conn = db.get_conn()
    conn.execute("UPDATE notifications SET read = 1 WHERE tg_id = ?", (update.effective_user.id,))
    conn.commit()
    conn.close()
    await query.message.edit_text("All marked read.")

async def callback_help(update, context):
    query = update.callback_query
    await query.answer()
    text = (f"Buugereydy VPN Manager\n\n"
            f"/start - Start bot\n"
            f"/menu - Main menu\n"
            f"/add - Quick add user\n"
            f"/analytics - Quick analytics\n"
            f"/stats - Server stats\n"
            f"/link - Your link\n"
            f"/myinfo - Your info\n\n"
            f"Use buttons below to navigate.")
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Main Menu", callback_data="back")],
    ]))

async def callback_restart_xray(update, context):
    query = update.callback_query
    await query.answer()
    xray.reload_xray()
    await query.message.edit_text("Xray restarted!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_stop_xray(update, context):
    query = update.callback_query
    await query.answer()
    xray.stop_xray()
    await query.message.edit_text("Xray stopped.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_start_xray(update, context):
    query = update.callback_query
    await query.answer()
    xray.start_xray()
    await query.message.edit_text("Xray started!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_server")]]))

async def callback_set_admin(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(f"Add admin TG ID (numeric):\nCurrent: {', '.join(str(a) for a in db.get_admin_tg_ids())}")

# === TEXT INPUT HANDLERS ===

async def handle_text(update, context):
    text = update.message.text.strip()
    step = context.user_data.get("_au_step")
    tg_id = update.effective_user.id

    if step == "au_lc":
        try:
            mb = int(text)
            context.user_data["_au_limit"] = mb
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("1 Day", callback_data="au_ep:1d"),
                 InlineKeyboardButton("3 Days", callback_data="au_ep:3d")],
                [InlineKeyboardButton("1 Week", callback_data="au_ep:1w"),
                 InlineKeyboardButton("2 Weeks", callback_data="au_ep:2w")],
                [InlineKeyboardButton("1 Month", callback_data="au_ep:1m"),
                 InlineKeyboardButton("3 Months", callback_data="au_ep:3m")],
                [InlineKeyboardButton("6 Months", callback_data="au_ep:6m"),
                 InlineKeyboardButton("1 Year", callback_data="au_ep:1y")],
                [InlineKeyboardButton("Custom", callback_data="au_ec")],
                [InlineKeyboardButton("None", callback_data="au_en")],
                [InlineKeyboardButton("Back", callback_data="add_user")],
            ])
            await update.message.reply_text(f"Limit: {fmt_mb(mb)}\n\nSelect expiry:", reply_markup=kb)
        except ValueError:
            await update.message.reply_text("Valid number in MB:")
        return

    if step == "au_ec":
        context.user_data["_au_expiry"] = text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Chain Proxy", callback_data="au_chain")],
            [InlineKeyboardButton("Done & Create", callback_data="au_done")],
            [InlineKeyboardButton("Back", callback_data="add_user")],
        ])
        await update.message.reply_text(f"Expiry: {text}\n\nSet chain or tap Done:", reply_markup=kb)
        return

    if step == "chain":
        context.user_data["_au_chain"] = text
        email = context.user_data.get("_au_email", "user_" + str(uuid.uuid4())[:8])
        limit = context.user_data.get("_au_limit", 0)
        expiry = context.user_data.get("_au_expiry")
        chain = text
        new_uuid = str(uuid.uuid4())
        db.add_user(new_uuid, email, limit, expiry, chain)
        xray.reload_xray()
        link = config_link(email, new_uuid)
        await update.message.reply_text(
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

    if step == "edit_limit_custom":
        email = context.user_data.get("_edit_email")
        try:
            mb = int(text)
            db.update_user_by_email(email, data_limit_mb=mb)
            xray.reload_xray()
            await update.message.reply_text(f"Limit set: {fmt_mb(mb)} for {email}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))
        except ValueError:
            await update.message.reply_text("Valid MB number:")
        return

    if step == "edit_exp_custom":
        email = context.user_data.get("_edit_email")
        db.update_user_by_email(email, expiry_date=text)
        xray.reload_xray()
        await update.message.reply_text(f"Expiry set: {text} for {email}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))
        return

    bl_type = context.user_data.get("_bl_type")
    if bl_type == "domain":
        if text.lower() == "back":
            context.user_data.pop("_bl_type")
            await update.message.reply_text("Back to blacklist.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.add_blacklist("domain", text, source="tg:" + str(tg_id))
        await update.message.reply_text(f"Domain blacklisted: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="bl_domains")]]))
        return

    if bl_type == "ip":
        if text.lower() == "back":
            context.user_data.pop("_bl_type")
            await update.message.reply_text("Back to blacklist.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.add_blacklist("ip", text, source="tg:" + str(tg_id))
        await update.message.reply_text(f"IP blacklisted: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="bl_ips")]]))
        return

    chain_type = context.user_data.get("_chain_type")
    if chain_type == "http":
        if text.lower() == "back":
            context.user_data.pop("_chain_type")
            await update.message.reply_text("Back to chain settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("chain_proxy", text)
        xray.reload_xray()
        await update.message.reply_text(f"HTTP chain: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_chain")]]))
        return

    if chain_type == "socks":
        if text.lower() == "back":
            context.user_data.pop("_chain_type")
            await update.message.reply_text("Back to chain settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("chain_proxy", text)
        xray.reload_xray()
        await update.message.reply_text(f"SOCKS chain: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_chain")]]))
        return

    dns_type = context.user_data.get("_dns_type")
    if dns_type == "custom":
        if text.lower() == "back":
            context.user_data.pop("_dns_type")
            await update.message.reply_text("Back to DNS settings.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
            return
        db.set_setting("dns_server", text)
        xray.reload_xray()
        await update.message.reply_text(f"DNS set: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="set_dns")]]))
        return

    batch_step = context.user_data.get("_batch_step")
    if batch_step == "bl_custom":
        try:
            mb = int(text)
            users = db.get_limit_users()
            for u in users:
                db.update_user_by_email(u["email"], data_limit_mb=mb)
            xray.reload_xray()
            await update.message.reply_text(f"Set {fmt_mb(mb)} for {len(users)} users",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))
            context.user_data.pop("_batch_step")
        except ValueError:
            await update.message.reply_text("Valid MB number:")
        return

    if batch_step == "be_custom":
        expiry = text
        users = db.get_all_users()
        for u in users:
            db.update_user_by_email(u["email"], expiry_date=expiry)
        xray.reload_xray()
        await update.message.reply_text(f"Expiry {expiry} for {len(users)} users",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="batch_ops")]]))
        context.user_data.pop("_batch_step")
        return

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
        if text.lower() == "back":
            await update.message.reply_text("Cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
        else:
            await update.message.reply_text("Numeric ID only:")

# === COMMANDS ===

async def start(update, context):
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

async def menu(update, context):
    await update.message.reply_text("Main menu:", reply_markup=main_markup())

async def help(update, context):
    await update.message.reply_text(
        "/start - Start bot\n"
        "/menu - Main menu\n"
        "/add - Quick add user\n"
        "/analytics - Quick analytics\n"
        "/stats - Server stats\n"
        "/link - Get your link\n"
        "/myinfo - Your user info\n"
        "/search - Search users\n")

async def add_quick(update, context):
    context.user_data["_au_step"] = "email"
    await update.message.reply_text("Enter email/name for new user:")

async def link_cmd(update, context):
    tg_id = update.effective_user.id
    users = db.get_all_users()
    tg_users = [u for u in users if u.get("tg_id") == tg_id or u.get("tg_username") == update.effective_user.username]
    if not tg_users:
        await update.message.reply_text("No users linked to you.\n\nUse /add to create one.")
        return
    user = tg_users[0]
    link = config_link(user["email"], user["uuid"])
    await update.message.reply_text(f"Your link:\n\n{link}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("QR", callback_data=f"view_qr:{user['email']}")]]))

async def myinfo(update, context):
    tg_id = update.effective_user.id
    users = db.get_all_users()
    tg_users = [u for u in users if u.get("tg_id") == tg_id or u.get("tg_username") == update.effective_user.username]
    if not tg_users:
        await update.message.reply_text("No users linked to you.")
        return
    user = tg_users[0]
    await update.message.reply_text(user_detail_text(user),
        reply_markup=user_detail_markup(user["email"]))

async def analytics_cmd(update, context):
    await update.message.reply_text("Analytics:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("View", callback_data="analytics")],
    ]))

async def stats_cmd(update, context):
    await update.message.reply_text("Server Stats:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("View", callback_data="server_stats")],
    ]))

async def search_cmd(update, context):
    context.user_data["_search_step"] = True
    await update.message.reply_text("Enter search term for user email:")

# === CODESPACE KEEPALIVE ===

async def keepalive_loop():
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
            await asyncio.sleep(600)

async def codespace_checker(application):
    import aiohttp
    print("[checker] Codespace health check starting (every 15 min)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get("https://api.github.com/repos", timeout=10) as resp:
                    if resp.status == 200:
                        uptime = time.time() - application._up_time if hasattr(application, '_up_time') else 0
                        print(f"[checker] OK - uptime: {int(uptime)}s at {datetime.now().strftime('%H:%M')}")
            except Exception as e:
                print(f"[checker] Fail: {e}")
            await asyncio.sleep(900)

# === CALLBACK ROUTER ===

async def callback_query(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    msg = query.message

    if data == "back":
        await callback_back(update, context)
        return

    handlers = {
        "add_user": callback_add_user,
        "au_limit": callback_add_user_limit,
        "au_lc": callback_add_user_limit_custom,
        "au_ln": callback_add_user_limit_none,
        "au_expiry": callback_add_user_expiry,
        "au_ec": callback_add_user_expiry_custom,
        "au_en": callback_add_user_expiry_none,
        "au_chain": callback_add_user_chain,
        "au_done": callback_add_user_done,
        "all_users": callback_all_users,
        "analytics": callback_analytics,
        "export_csv": callback_export_csv,
        "config_mgmt": callback_config_mgmt,
        "gen_links": callback_gen_links,
        "all_links": callback_all_links,
        "export_config": callback_export_config,
        "reload_config": callback_reload_config,
        "blacklist": callback_blacklist,
        "bl_domains": callback_bl_domains,
        "bl_add_domain": callback_bl_add_domain,
        "bl_ips": callback_bl_ips,
        "bl_add_ip": callback_bl_add_ip,
        "bl_users": callback_bl_users,
        "settings": callback_settings,
        "set_chain": callback_set_chain,
        "chain_current": callback_chain_current,
        "chain_http": callback_chain_http,
        "chain_socks": callback_chain_socks,
        "chain_remove": callback_chain_remove,
        "set_dns": callback_set_dns,
        "dns_cf": callback_dns_cf,
        "dns_google": callback_dns_google,
        "dns_quad9": callback_dns_quad9,
        "dns_custom": callback_dns_custom,
        "set_domain_bl": callback_set_domain_bl,
        "set_routing": callback_set_routing,
        "route_bt": callback_route_bt,
        "route_ads": callback_route_ads,
        "route_priv": callback_route_priv,
        "route_sniff": callback_route_sniff,
        "set_server": callback_set_server,
        "set_backup": callback_backup,
        "backup_config": callback_backup_config,
        "restore_config": callback_restore_config,
        "export_db": callback_export_db,
        "import_db": callback_import_db,
        "backup_users": callback_backup_users,
        "server_stats": callback_server_stats,
        "sys_info": callback_sys_info,
        "net_stats": callback_net_stats,
        "online_users": callback_online_users,
        "notifications": callback_notifications,
        "notif_readall": callback_notif_readall,
        "help_menu": callback_help,
        "batch_ops": callback_batch_ops,
        "batch_limit": callback_batch_limit,
        "batch_expiry": callback_batch_expiry,
        "batch_enable": callback_batch_enable,
        "batch_disable": callback_batch_disable,
        "batch_blacklist": callback_batch_blacklist,
        "batch_reset": callback_batch_reset,
        "set_admin": callback_set_admin,
    }

    if data.startswith("au_lp:"):
        await callback_add_user_limit_preset(update, context)
        return
    if data.startswith("au_ep:"):
        await callback_add_user_expiry_preset(update, context)
        return
    if data.startswith("user_detail:"):
        await callback_user_detail(update, context)
        return
    if data.startswith("edit_limit:"):
        await callback_edit_limit(update, context)
        return
    if data.startswith("limit_set:"):
        await callback_limit_set(update, context)
        return
    if data.startswith("limit_custom:"):
        await callback_limit_custom(update, context)
        return
    if data.startswith("limit_unset:"):
        await callback_limit_unset(update, context)
        return
    if data.startswith("edit_expiry:"):
        await callback_edit_expiry(update, context)
        return
    if data.startswith("exp_set:"):
        await callback_expiry_set(update, context)
        return
    if data.startswith("exp_custom:"):
        await callback_expiry_custom(update, context)
        return
    if data.startswith("exp_unset:"):
        await callback_expiry_unset(update, context)
        return
    if data.startswith("toggle_block:"):
        await query.answer()
        email = data.split(":")[1]
        u = db.get_user_by_email(email)
        db.update_user_by_email(email, blacklist=0 if u["blacklist"] else 1)
        xray.reload_xray()
        await query.message.edit_text(f"{'Blacklisted' if not u['blacklist'] else 'Unblocked'}: {email}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"user_detail:{email}")]]))
        return
    if data.startswith("reset_data:"):
        await callback_reset_data(update, context)
        return
    if data.startswith("toggle_enable:"):
        await callback_toggle_enable(update, context)
        return
    if data.startswith("view_link:"):
        await callback_view_link(update, context)
        return
    if data.startswith("view_qr:"):
        await callback_view_qr(update, context)
        return
    if data.startswith("traffic:"):
        await callback_traffic(update, context)
        return
    if data.startswith("del_user:"):
        await callback_del_user(update, context)
        return
    if data.startswith("analytics:"):
        await callback_analytics(update, context)
        return
    if data.startswith("notif_read:"):
        await callback_notif_read(update, context)
        return
    if data.startswith("p_"):
        await callback_ss_port_set(update, context)
        return
    if data.startswith("n_"):
        await callback_ss_net_set(update, context)
        return
    if data.startswith("s_"):
        await callback_ss_sec_set(update, context)
        return
    if data.startswith("m_"):
        await callback_ss_mode_set(update, context)
        return
    if data.startswith("bl:"):
        await callback_batch_limit_preset(update, context)
        return
    if data == "bl_custom":
        await callback_batch_limit_custom(update, context)
        return
    if data.startswith("be:"):
        await callback_batch_expiry_preset(update, context)
        return
    if data == "be_custom":
        await callback_batch_expiry_custom(update, context)
        return
    if data == "restart_xray":
        await callback_restart_xray(update, context)
        return
    if data == "stop_xray":
        await callback_stop_xray(update, context)
        return
    if data == "start_xray":
        await callback_start_xray(update, context)
        return

    handler = handlers.get(data)
    if handler:
        await handler(update, context)
        return

    await query.message.edit_text("Unknown command.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))

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
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("myinfo", myinfo))
    app.add_handler(CommandHandler("search", search_cmd))

    async def stats(update, context):
        await update.message.reply_text("Server Stats:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("View", callback_data="server_stats")],
        ]))
    app.add_handler(CommandHandler("stats", stats))

    async def analytics(update, context):
        await update.message.reply_text("Analytics:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("View", callback_data="analytics")],
        ]))
    app.add_handler(CommandHandler("analytics", analytics))

    app.add_handler(CallbackQueryHandler(callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if not xray.check_xray_running():
        print("[buugereydy] Starting Xray...")
        xray.start_xray()

    import threading
    threading.Thread(target=lambda: asyncio.run(keepalive_loop()), daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(codespace_checker(app)), daemon=True).start()

    print("[buugereydy] Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
