#!/bin/bash
# VM startup script for the FORBIDDEN-COUNTRY LISTENER VM (runs as root at every boot).
set -euo pipefail
md() { curl -sf -H "Metadata-Flavor: Google" \
       "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
REPO=$(md repo); BUCKET=$(md bucket); PROJECT=$(curl -sf -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/project/project-id); SUB=$(md subscription)

apt-get update -y && apt-get install -y python3-venv git
id hw4 >/dev/null 2>&1 || useradd --system --home-dir /opt/hw4 --shell /usr/sbin/nologin hw4
mkdir -p /opt/hw4
rm -rf /opt/hw4/repo && git clone --depth 1 "$REPO" /opt/hw4/repo
[ -x /opt/hw4/venv/bin/python ] || python3 -m venv /opt/hw4/venv
/opt/hw4/venv/bin/pip install -q -r /opt/hw4/repo/listener/requirements.txt

cat > /etc/systemd/system/hw4-listener.service <<UNIT
[Unit]
Description=HW4 forbidden-country listener
After=network-online.target
Wants=network-online.target

[Service]
User=hw4
ExecStart=/opt/hw4/venv/bin/python -u /opt/hw4/repo/listener/forbidden_listener.py --project $PROJECT --subscription $SUB --bucket $BUCKET
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable hw4-listener
systemctl restart hw4-listener
