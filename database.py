import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path("/tmp/buugereydy.db")

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        uuid TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        tg_id INTEGER,
        tg_username TEXT,
        data_limit_mb INTEGER DEFAULT 0,
        data_used_mb REAL DEFAULT 0,
        reset_day INTEGER DEFAULT 1,
        expiry_date TEXT,
        enabled INTEGER DEFAULT 1,
        blacklist INTEGER DEFAULT 0,
        created_at REAL DEFAULT 0,
        last_seen REAL DEFAULT 0,
        total_connects INTEGER DEFAULT 0,
        chain_proxy TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT,
        connected_at REAL DEFAULT 0,
        disconnected_at REAL,
        bytes_up REAL DEFAULT 0,
        bytes_down REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        value TEXT NOT NULL,
        source TEXT,
        created_at REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER,
        action TEXT,
        details TEXT,
        timestamp REAL DEFAULT 0
    )""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_connections_uuid ON connections(uuid)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp)""")
    # Set default settings
    defaults = {
        "chain_outbound_tag": "chain",
        "chain_proxy": "",
        "dns_server": "https://1.1.1.1/dns-query",
        "dns_domain_strategy": "UseIP",
        "bittorrent_block": "1",
        "ads_block": "1",
        "private_ip_block": "1",
        "sniffing_enabled": "1",
        "xray_port": "443",
        "xray_network": "xhttp",
        "xray_security": "none",
        "xray_mode": "packet-up",
        "max_clients": "100",
        "stats_api_key": "",
        "auto_reset_day": "1",
        "notify_on_limit": "1",
        "notify_on_expiry": "1",
        "keepalive_interval": "180",
        "config_name": "BUUGEREYDY",
        "admin_tg_ids": ""
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def add_user(uuid, email, data_limit_mb=0, expiry_date=None, chain_proxy=""):
    conn = get_conn()
    c = conn.cursor()
    now = time.time()
    c.execute("""INSERT INTO users (uuid, email, created_at, expiry_date, chain_proxy)
                 VALUES (?, ?, ?, ?, ?)""",
              (uuid, email, now, expiry_date, chain_proxy))
    conn.commit()
    conn.close()

def get_user(uuid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_user(uuid, **kwargs):
    conn = get_conn()
    c = conn.cursor()
    allowed = {"email","data_limit_mb","data_used_mb","expiry_date","enabled",
               "blacklist","last_seen","total_connects","chain_proxy"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if sets:
        vals.append(uuid)
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE uuid = ?", vals)
        conn.commit()
    conn.close()

def delete_user(uuid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE uuid = ?", (uuid,))
    conn.commit()
    conn.close()

def get_user_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM users")
    r = c.fetchone()["cnt"]
    conn.close()
    return r

def get_enabled_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE enabled = 1 ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_expired_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE expiry_date IS NOT NULL AND expiry_date != ''")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_limit_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE data_limit_mb > 0")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def reset_user_data(uuid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET data_used_mb = 0 WHERE uuid = ?", (uuid,))
    conn.commit()
    conn.close()

def set_data_used(uuid, up, down):
    conn = get_conn()
    c = conn.cursor()
    total = (up + down) / (1024 * 1024)
    c.execute("UPDATE users SET data_used_mb = ? WHERE uuid = ?", (total, uuid))
    conn.commit()
    conn.close()

def log_action(tg_id, action, details=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO audit_log (tg_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
              (tg_id, action, details, time.time()))
    conn.commit()
    conn.close()

def log_connection(uuid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO connections (uuid, connected_at) VALUES (?, ?)",
              (uuid, time.time()))
    conn.commit()
    conn.close()

def close_connection(uuid, bytes_up=0, bytes_down=0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE connections SET disconnected_at = ?, bytes_up = ?, bytes_down = ?
                 WHERE uuid = ? AND disconnected_at IS NULL
                 ORDER BY connected_at DESC LIMIT 1""",
              (time.time(), bytes_up, bytes_down, uuid))
    conn.commit()
    conn.close()

def get_connection_stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT uuid, MAX(connected_at) as last_conn FROM connections
                 WHERE disconnected_at IS NULL GROUP BY uuid""")
    active = [dict(r) for r in c.fetchall()]
    c.execute("SELECT COUNT(*) as cnt FROM connections WHERE disconnected_at IS NULL")
    total_active = c.fetchone()["cnt"]
    conn.close()
    return {"active": active, "count": total_active}

def get_analytics(days=7):
    conn = get_conn()
    c = conn.cursor()
    cutoff = time.time() - (days * 86400)
    c.execute("""SELECT u.uuid, u.email, u.data_limit_mb, u.data_used_mb,
                      u.total_connects, u.last_seen, u.created_at,
                      COUNT(c.id) as conn_count
                 FROM users u
                 LEFT JOIN connections c ON u.uuid = c.uuid AND c.connected_at >= ?
                 GROUP BY u.uuid
                 ORDER BY conn_count DESC""", (cutoff,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_blacklist(type_, value, source=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO blacklist (type, value, source, created_at) VALUES (?, ?, ?, ?)",
              (type_, value, source, time.time()))
    conn.commit()
    conn.close()

def remove_blacklist(type_, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM blacklist WHERE type = ? AND value = ?", (type_, value))
    conn.commit()
    conn.close()

def get_blacklist(type_=""):
    conn = get_conn()
    c = conn.cursor()
    if type_:
        c.execute("SELECT * FROM blacklist WHERE type = ?", (type_,))
    else:
        c.execute("SELECT * FROM blacklist ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_setting(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    r = c.fetchone()
    conn.close()
    return r["value"] if r else None

def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_admin_tg_ids():
    val = get_setting("admin_tg_ids")
    if not val:
        return []
    return [int(x.strip()) for x in val.split(",") if x.strip()]

# --- Email-based helpers (used by bot.py) ---

def get_user_by_email(email):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user_by_email(email, **kwargs):
    conn = get_conn()
    c = conn.cursor()
    allowed = {"email","data_limit_mb","data_used_mb","expiry_date","enabled",
               "blacklist","last_seen","total_connects","chain_proxy"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if sets:
        vals.append(email)
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE email = ?", vals)
        conn.commit()
    conn.close()

def delete_user_by_email(email):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    conn.close()
