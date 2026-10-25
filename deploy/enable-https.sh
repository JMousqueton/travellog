#!/bin/sh
# Obtient le certificat Let's Encrypt de travellog.julien.io puis active la configuration HTTPS.
# Prérequis : enregistrements DNS travellog.julien.io -> 213.32.17.149 (A) et 2001:41d0:305:2100::1:1c4b (AAAA).
set -eu
DOMAIN=travellog.julien.io
HERE=$(cd "$(dirname "$0")" && pwd)

if ! getent hosts "$DOMAIN" >/dev/null; then
  echo "Le domaine $DOMAIN ne résout pas encore : ajoutez l'enregistrement DNS puis relancez." >&2
  exit 1
fi
sudo certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive --agree-tos --keep-until-expiring \
  --deploy-hook "systemctl reload nginx"
sudo cp "$HERE/nginx/$DOMAIN.conf" "/etc/nginx/sites-available/$DOMAIN.conf"
sudo nginx -t
sudo systemctl reload nginx
echo "https://$DOMAIN est en ligne."
