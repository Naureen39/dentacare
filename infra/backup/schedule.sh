#!/bin/sh
# Run backup.sh every night at BACKUP_HOUR:BACKUP_MINUTE (UTC, default 02:30) and keep going if
# one run fails, so a bad night does not stop the next.
set -u

HOUR="${BACKUP_HOUR:-02}"
MINUTE="${BACKUP_MINUTE:-30}"

while true; do
  now=$(date -u +%s)
  next=$(date -u -d "$(date -u +%Y-%m-%d) $HOUR:$MINUTE:00" +%s 2>/dev/null || echo $((now + 86400)))
  [ "$next" -le "$now" ] && next=$((next + 86400))
  echo "next backup at $(date -u -d "@$next" '+%Y-%m-%d %H:%M UTC')"
  sleep $((next - now))
  /scripts/backup.sh || echo "backup failed, will try again tomorrow" >&2
done
