#!/bin/sh
# Obtient le certificat Let's Encrypt de voyage-voyage.app (et www) puis active la configuration HTTPS.
# Prérequis : enregistrements DNS voyage-voyage.app et www -> 213.32.17.149 (A) et 2001:41d0:305:2100::1:1c4b (AAAA).
set -eu
DOMAIN=voyage-voyage.app
HERE=$(cd "$(dirname "$0")" && pwd)

for name in "$DOMAIN" "www.$DOMAIN"; do
  if ! getent hosts "$name" >/dev/null; then
    echo "Le domaine $name ne résout pas encore : ajoutez l'enregistrement DNS puis relancez." >&2
    exit 1
  fi
done
sudo certbot certonly --webroot -w /var/www/html -d "$DOMAIN" -d "www.$DOMAIN" --cert-name "$DOMAIN" \
  --non-interactive --agree-tos --keep-until-expiring --deploy-hook "systemctl reload nginx"
sudo cp "$HERE/nginx/$DOMAIN.conf" "/etc/nginx/sites-available/$DOMAIN.conf"
sudo ln -sf "/etc/nginx/sites-available/$DOMAIN.conf" "/etc/nginx/sites-enabled/$DOMAIN.conf"
# L'ancienne configuration (travellog.julien.io) est reprise dans la nouvelle.
sudo rm -f /etc/nginx/sites-enabled/travellog.julien.io.conf
sudo nginx -t
sudo systemctl reload nginx
echo "https://$DOMAIN est en ligne."
