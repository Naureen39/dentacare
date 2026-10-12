#!/bin/sh
# Make one backup of the database: a compressed pg_dump file, checked by reading it back.
#
#   PGHOST, PGUSER, PGPASSWORD, PGDATABASE   which database (the usual libpq variables)
#   BACKUP_DIR                               where files go (default /backups)
#   BACKUP_KEEP_DAYS                         how long to keep them (default 14)
set -eu

DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="$DIR/${PGDATABASE:-meridian}-$STAMP.dump"

mkdir -p "$DIR"
# Write to a temporary name first, so a half written file is never mistaken for a backup.
pg_dump --format=custom --no-owner --file="$FILE.partial"
# A dump that cannot be listed cannot be restored: refuse to keep it.
if ! pg_restore --list "$FILE.partial" > /dev/null; then
  rm -f "$FILE.partial"
  echo "backup failed: the dump could not be read back" >&2
  exit 1
fi
mv "$FILE.partial" "$FILE"
echo "backup written: $FILE ($(wc -c < "$FILE") bytes)"

# Remove backups older than the retention period.
find "$DIR" -name '*.dump' -type f -mtime "+$KEEP" -print -delete
