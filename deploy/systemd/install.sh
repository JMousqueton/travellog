#!/bin/sh
# Installe les timers des tâches périodiques et retire les lignes cron qu'ils remplacent.
# Usage : sudo deploy/systemd/install.sh
set -eu
here=$(dirname "$0")
cp "$here"/travellog-job@.service "$here"/travellog-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now travellog-mail-import.timer travellog-backup.timer travellog-maintenance.timer
# Anciennes tâches cron de l'utilisateur ubuntu (mail-import, backup create) : désormais en timers.
if crontab -u ubuntu -l >/dev/null 2>&1; then
  crontab -u ubuntu -l | grep -v -e 'flask mail-import' -e 'flask backup create' \
    -e '^# Import de voyages par e-mail' -e '^# Carnet de voyages : sauvegarde' | crontab -u ubuntu -
fi
systemctl list-timers 'travellog-*'
