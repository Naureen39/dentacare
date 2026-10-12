#!/bin/sh
# Prove a backup can be restored: load the newest dump (or the one given) into a scratch
# database, compare the row count of every table with the live database, then drop the scratch
# database. Exits with an error when anything differs.
#
#   restore_test.sh [dump file]
#
# Uses the same PG* variables as backup.sh. Needs permission to create a database.
set -eu

DIR="${BACKUP_DIR:-/backups}"
SOURCE="${PGDATABASE:-meridian}"
SCRATCH="${SOURCE}_restore_check"
FILE="${1:-$(ls -1t "$DIR"/*.dump | head -n 1)}"

echo "restoring $FILE into $SCRATCH"
psql -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" -c "CREATE DATABASE \"$SCRATCH\""
trap 'psql -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" > /dev/null' EXIT

# The extensions are created by the dump itself. Errors about objects that already exist in a
# fresh database are not expected, so any error stops the test.
pg_restore --no-owner --exit-on-error --dbname="$SCRATCH" "$FILE"

counts() {
  psql -At -d "$1" -c "
    SELECT format('%s=%s', table_name,
                  (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1])
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name"
}

counts "$SOURCE" > /tmp/live.counts
counts "$SCRATCH" > /tmp/restored.counts

if diff /tmp/live.counts /tmp/restored.counts > /tmp/diff.txt; then
  tables=$(wc -l < /tmp/restored.counts)
  echo "restore test passed: $tables tables, every row count matches"
else
  echo "restore test FAILED: row counts differ" >&2
  cat /tmp/diff.txt >&2
  exit 1
fi
