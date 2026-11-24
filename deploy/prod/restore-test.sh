#!/bin/bash
# Prove a backup can actually be restored.  Usage:  ./restore-test.sh <dump file | s3://bucket/key>
# Restores into a scratch database (never touches the live one) and compares row counts with the live database.
# COMPOSE_FILE selects the stack (default: the production compose file; for a local test use ../../docker-compose.yml).
set -euo pipefail
SRC=${1:?dump file or s3 uri}
export COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
PG() { docker compose ${ENV_FILE:+--env-file $ENV_FILE} exec -T postgres "$@"; }
if [[ $SRC == s3://* ]]; then aws s3 cp "$SRC" /tmp/restore.dump --only-show-errors; SRC=/tmp/restore.dump; fi
PG psql -U conduit -d postgres -qc "DROP DATABASE IF EXISTS restore_test" -c "CREATE DATABASE restore_test"
PG pg_restore -U conduit -d restore_test --no-owner < "$SRC"
echo "table            live   restored"
OK=1
for t in tenants api_keys jobs usage prompt_versions; do
  live=$(PG psql -U conduit -d conduit -Atc "SELECT count(*) FROM $t")
  rest=$(PG psql -U conduit -d restore_test -Atc "SELECT count(*) FROM $t")
  printf "%-14s %6s %9s\n" "$t" "$live" "$rest"
  [ "$live" = "$rest" ] || OK=0
done
PG psql -U conduit -d postgres -qc "DROP DATABASE restore_test"
[ $OK = 1 ] && echo "RESTORE TEST PASSED (row counts match)" || { echo "RESTORE TEST: counts differ (expected if the live DB changed since the dump was taken)"; exit 1; }
