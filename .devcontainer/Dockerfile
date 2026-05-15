FROM debian:bookworm-slim

COPY setup.sh /tmp/setup.sh
COPY config.json /etc/xray/g2ray.json
COPY show-link.sh /usr/local/bin/show-link.sh
COPY start.sh /usr/local/bin/start.sh
COPY bot.py /root/buugereydyfinal/bot.py
COPY xray_manager.py /root/buugereydyfinal/xray_manager.py
COPY database.py /root/buugereydyfinal/database.py
COPY requirements.txt /root/buugereydyfinal/requirements.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash curl wget unzip ca-certificates openssl uuid-runtime tmux \
       python3 python3-pip git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /etc/xray \
    && mkdir -p /root/buugereydyfinal \
    && pip3 install --no-cache-dir -r /root/buugereydyfinal/requirements.txt \
    && chmod +x /tmp/setup.sh \
    && /tmp/setup.sh \
    && rm /tmp/setup.sh \
    && chmod +x /usr/local/bin/show-link.sh \
    && chmod +x /usr/local/bin/start.sh

EXPOSE 443

CMD ["/usr/local/bin/xray","run","-c","/etc/xray/g2ray.json"]
