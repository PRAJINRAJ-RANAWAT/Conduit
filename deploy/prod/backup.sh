#!/bin/bash
# Nightly: dump Postgres and upload to S3 (the bucket expires old dumps by itself; see infra/terraform/s3.tf).
# Run by the conduit-backup.timer systemd timer (03:15 UTC). Usage: /opt/conduit/backup.sh
set -euo pipefail
cd /opt/conduit
set -a; . ./.env; set +a
FILE=/tmp/conduit-$(date -u +%Y%m%dT%H%M%SZ).dump
docker compose -f docker-compose.prod.yml --env-file .env exec -T postgres pg_dump -U conduit -Fc conduit > "$FILE"
aws s3 cp "$FILE" "s3://${BACKUP_BUCKET}/pg/$(basename "$FILE")" --only-show-errors
rm -f "$FILE"
echo "backup uploaded: $(basename "$FILE")"
