#!/bin/bash
# One-time: get a Let's Encrypt certificate.  Usage: /opt/conduit/init-tls.sh <domain> <email>
# Needs: DNS for <domain> already points at this server's Elastic IP, ports 80/443 open (the security group allows them).
# Trick: nginx will not start without a certificate, and certbot needs nginx to answer the challenge on port 80.
# So: make a throw-away self-signed cert -> start nginx -> ask for the real cert -> reload nginx.
set -euo pipefail
DOMAIN=${1:?domain}; EMAIL=${2:?email}
cd /opt/conduit
dc() { docker compose -f docker-compose.prod.yml --env-file .env "$@"; }
grep -q '^DOMAIN=' .env || echo "DOMAIN=$DOMAIN" >> .env
dc run --rm --no-deps --entrypoint sh certbot -c "
  mkdir -p /etc/letsencrypt/live/$DOMAIN &&
  apk add -q openssl 2>/dev/null; openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj /CN=localhost \
    -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
dc up -d nginx
sleep 3
dc run --rm --no-deps --entrypoint sh certbot -c "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
dc run --rm certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email -n
dc exec -T nginx nginx -s reload
echo "certificate installed for $DOMAIN; renewal runs from the conduit-certbot.timer systemd timer"
