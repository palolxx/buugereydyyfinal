import json
import uuid
import subprocess
import os
import time
from pathlib import Path
import database as db

CONFIG_PATH = Path("/etc/xray/g2ray.json")
XRAY_BIN = "/usr/local/bin/xray"
GEOIP_PATH = Path("/usr/local/bin/geoip.dat")
GEOSITE_PATH = Path("/usr/local/bin/geosite.dat")

def get_default_config():
    return {
        "log": {
            "loglevel": "warning",
            "access": "none",
            "error": "/tmp/xray-error.log"
        },
        "dns": {
            "servers": [
                {
                    "address": db.get_setting("dns_server") or "https://1.1.1.1/dns-query",
                    "domains": ["geosite:geolocation-!cn"],
                    "queryStrategy": db.get_setting("dns_domain_strategy") or "UseIP"
                },
                "8.8.8.8",
                "localhost"
            ],
            "queryStrategy": "UseIPv4"
        },
        "inbounds": [],
        "outbounds": [
            {
                "tag": "direct",
                "protocol": "freedom",
                "settings": {"domainStrategy": "UseIPv4"}
            },
            {
                "tag": "block",
                "protocol": "blackhole",
                "settings": {"response": {"type": "http"}}
            }
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": []
        },
        "policy": {
            "levels": {
                "0": {
                    "handshake": 4,
                    "connIdle": 300,
                    "uplinkOnly": 2,
                    "downlinkOnly": 5,
                    "bufferSize": 512
                }
            }
        }
    }

def _build_routing_rules():
    rules = []
    if db.get_setting("private_ip_block") == "1":
        rules.append({
            "type": "field",
            "ip": ["geoip:private"],
            "outboundTag": "block"
        })
    if db.get_setting("bittorrent_block") == "1":
        rules.append({
            "type": "field",
            "protocol": ["bittorrent"],
            "outboundTag": "block"
        })
    if db.get_setting("ads_block") == "1":
        rules.append({
            "type": "field",
            "domain": ["geosite:category-ads-all"],
            "outboundTag": "block"
        })
    # Add domain blacklist from DB
    for item in db.get_blacklist("domain"):
        rules.append({
            "type": "field",
            "domain": [f"regexp:{item['value']}"],
            "outboundTag": "block"
        })
    return rules

def _build_inbounds():
    inbounds = []
    port = int(db.get_setting("xray_port") or "443")
    network = db.get_setting("xray_network") or "xhttp"
    security = db.get_setting("xray_security") or "none"
    mode = db.get_setting("xray_mode") or "packet-up"

    for user in db.get_enabled_users():
        inbound = {
            "tag": f"vless-{user['uuid'][:8]}",
            "port": port,
            "listen": "0.0.0.0",
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "id": user["uuid"],
                        "flow": "",
                        "level": 0,
                        "email": user["email"]
                    }
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": network,
                "security": security,
                "xhttpSettings": {
                    "mode": mode,
                    "path": "/",
                    "maxUploadSize": 1000000,
                    "maxConcurrentUploads": 10
                }
            },
            "sniffing": {
                "enabled": db.get_setting("sniffing_enabled") == "1",
                "destOverride": ["http", "tls", "quic"],
                "routeOnly": False
            }
        }
        if security == "tls":
            inbound["streamSettings"]["tlsSettings"] = {
                "certificates": [
                    {
                        "certificateFile": "/root/.local/share/cert.crt",
                        "keyFile": "/root/.local/share/key.key"
                    }
                ]
            }
        inbounds.append(inbound)
    return inbounds

def _build_outbounds(chain_proxy=""):
    outbounds = [
        {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {"domainStrategy": "UseIPv4"}
        },
        {
            "tag": "block",
            "protocol": "blackhole",
            "settings": {"response": {"type": "http"}}
        }
    ]
    if chain_proxy:
        # Parse chain proxy: protocol://host:port
        proxy_tag = "chain-proxy"
        proxy_user, proxy_pass = "", ""
        if "://" in chain_proxy:
            scheme, rest = chain_proxy.split("://", 1)
            if "@" in rest:
                proxy_pass, rest = rest.split("@", 1)
                proxy_user, proxy_pass = proxy_pass.split(":", 1) if ":" in proxy_pass else (proxy_pass, "")
        if chain_proxy.startswith("http://") or chain_proxy.startswith("https://"):
            outbounds.append({
                "tag": proxy_tag,
                "protocol": "http",
                "settings": {
                    "servers": [{
                        "address": rest.split(":")[0],
                        "port": int(rest.split(":")[-1]) if ":" in rest else 80,
                        "users": [{"user": proxy_user, "pass": proxy_pass}] if proxy_user else []
                    }]
                }
            })
        elif chain_proxy.startswith("socks://") or chain_proxy.startswith("socks5://"):
            rest = chain_proxy.replace("socks://", "").replace("socks5://", "")
            outbounds.append({
                "tag": proxy_tag,
                "protocol": "socks",
                "settings": {
                    "servers": [{
                        "address": rest.split(":")[0],
                        "port": int(rest.split(":")[-1]) if ":" in rest else 1080,
                        "users": [{"user": proxy_user, "pass": proxy_pass}] if proxy_user else []
                    }]
                }
            })
        outbounds.append({
            "tag": "proxy",
            "protocol": "freedom",
            "settings": {"domainStrategy": "UseIPv4"}
        })
    return outbounds

def _build_user_routing_rules():
    rules = []
    for user in db.get_all_users():
        if user["blacklist"]:
            rules.append({
                "type": "field",
                "tag": f"vless-{user['uuid'][:8]}",
                "outboundTag": "block"
            })
    return rules

def generate_config():
    config = get_default_config()
    config["inbounds"] = _build_inbounds()
    config["outbounds"] = _build_outbounds()
    chain_proxy = db.get_setting("chain_proxy")
    if chain_proxy:
        config["outbounds"] = _build_outbounds(chain_proxy)
        # Add chain proxy outbound
        config["outbounds"].append({
            "tag": "chain",
            "protocol": "freedom",
            "settings": {"domainStrategy": "UseIPv4"},
            "proxySettings": {
                "tag": db.get_setting("chain_outbound_tag") or "chain-proxy"
            }
        })
    config["routing"]["rules"] = _build_routing_rules()
    config["routing"]["rules"].extend(_build_user_routing_rules())
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    return config

def start_xray():
    generate_config()
    subprocess.run(["sudo", XRAY_BIN, "run", "-c", str(CONFIG_PATH)],
                   stdout=open("/tmp/xray.log", "a"), stderr=subprocess.STDOUT,
                   start_new_session=True)
    time.sleep(2)
    return check_xray_running()

def stop_xray():
    subprocess.run(["sudo", XRAY_BIN, "run", "-c", str(CONFIG_PATH), "--kill"],
                   capture_output=True)
    time.sleep(1)
    return not check_xray_running()

def reload_xray():
    stop_xray()
    return start_xray()

def check_xray_running():
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        return "xray" in result.stdout
    except Exception:
        return False

def get_xray_stats():
    try:
        result = subprocess.run([XRAY_BIN, "api", "--stats"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None

def get_link_info(config=None):
    if not config:
        try:
            with open(CONFIG_PATH) as f:
                config = json.load(f)
        except:
            return None, None
    if not config.get("inbounds"):
        return None, None
    inbound = config["inbounds"][0]
    settings = inbound.get("settings", {})
    clients = settings.get("clients", [])
    if not clients:
        return None, None
    client = clients[0]
    uuid = client.get("id", "")
    network = inbound.get("streamSettings", {}).get("network", "xhttp")
    sni = os.environ.get("CODESPACE_NAME", "codespace")
    return {
        "uuid": uuid,
        "sni": f"{snI}-443.app.github.dev",
        "host": f"{snI}-443.app.github.dev",
        "port": inbound.get("port", 443),
        "network": network,
        "mode": inbound.get("streamSettings", {}).get("xhttpSettings", {}).get("mode", "packet-up"),
        "security": inbound.get("streamSettings", {}).get("security", "none")
    }

def get_all_links():
    config = generate_config()
    links = []
    for inbound in config.get("inbounds", []):
        settings = inbound.get("settings", {})
        clients = settings.get("clients", [])
        for client in clients:
            uuid = client.get("id", "")
            email = client.get("email", "user")
            info = get_link_info(config)
            if info:
                sni_host = info["host"]
                link = (f"vless://{uuid}@94.130.50.12:{info['port']}?"
                        f"encryption=none&security=tls&sni={sni_host}"
                        f"&host={sni_host}&fp=chrome&allowInsecure=1"
                        f"&type={info['network']}&mode={info['mode']}&path=%2F#{email}")
                links.append({"email": email, "uuid": uuid, "link": link})
    return links
