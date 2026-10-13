#!/bin/bash
# VM startup script for the WEB SERVER VM (runs as root at every boot).
# Installs Python deps, fetches the code from GitHub and starts the server as a
# systemd service, so it starts automatically on VM creation and after reboots.
set -euo pipefail
md() { curl -sf -H "Metadata-Flavor: Google" \
       "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
REPO=$(md repo); BUCKET=$(md bucket); PREFIX=$(md prefix || echo pages/); TOPIC=$(md topic)

apt-get update -y && apt-get install -y python3-venv git
id hw4 >/dev/null 2>&1 || useradd --system --home-dir /opt/hw4 --shell /usr/sbin/nologin hw4
mkdir -p /opt/hw4
rm -rf /opt/hw4/repo && git clone --depth 1 "$REPO" /opt/hw4/repo
[ -x /opt/hw4/venv/bin/python ] || python3 -m venv /opt/hw4/venv
/opt/hw4/venv/bin/pip install -q -r /opt/hw4/repo/server/requirements.txt

cat > /etc/systemd/system/hw4-web.service <<UNIT
[Unit]
Description=HW4 file web server
After=network-online.target
Wants=network-online.target

[Service]
User=hw4
# bind port 80 without running as root
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/opt/hw4/venv/bin/python -u /opt/hw4/repo/server/web_server.py --port 80 --bucket $BUCKET --prefix $PREFIX --topic $TOPIC
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable hw4-web
systemctl restart hw4-web
