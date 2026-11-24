#!/bin/bash
# Runs once, as root, when the instance first boots.
set -euxo pipefail
dnf install -y docker cronie jq
systemctl enable --now docker crond

# docker compose v2 plugin (ARM64 build)
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-aarch64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 2 GB swap: the box has only 2 GB of RAM, swap is the safety net for spikes
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /opt/conduit/bench
# systemd timers: nightly database backup, twice-daily certificate renewal check
cat > /etc/systemd/system/conduit-backup.service <<'UNIT'
[Unit]
Description=Conduit nightly Postgres backup to S3
[Service]
Type=oneshot
ExecStart=/opt/conduit/backup.sh
UNIT
cat > /etc/systemd/system/conduit-backup.timer <<'UNIT'
[Unit]
Description=Nightly Conduit backup
[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/conduit-certbot.service <<'UNIT'
[Unit]
Description=Renew Let's Encrypt certificate
[Service]
Type=oneshot
WorkingDirectory=/opt/conduit
ExecStart=/bin/bash -c 'docker compose -f docker-compose.prod.yml --env-file .env run --rm certbot renew --webroot -w /var/www/certbot && docker compose -f docker-compose.prod.yml --env-file .env exec -T nginx nginx -s reload'
UNIT
cat > /etc/systemd/system/conduit-certbot.timer <<'UNIT'
[Unit]
Description=Twice-daily certificate renewal check
[Timer]
OnCalendar=*-*-* 00,12:30:00
RandomizedDelaySec=1800
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now conduit-backup.timer conduit-certbot.timer
