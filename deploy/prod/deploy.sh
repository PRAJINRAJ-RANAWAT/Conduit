#!/bin/bash
# Runs ON the instance (started over SSM by the deploy workflow):  /opt/conduit/deploy.sh <image-tag>
# Steps: fetch secrets -> pull images -> start infra -> run migrations -> restart ONE gateway at a time with a
# health check in between -> start the rest. If a health check fails, go back to the previous tag.
set -uo pipefail
TAG=${1:?image tag}
cd /opt/conduit
PREV=$(cat .current_tag 2>/dev/null || true)
REGION=${AWS_REGION:-$(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/placement/region)}
export AWS_DEFAULT_REGION=$REGION

# 1. secrets + settings from SSM Parameter Store (never stored in git or in the workflow)
{ aws ssm get-parameters-by-path --path /conduit --with-decryption --query 'Parameters[].[Name,Value]' --output text |
    awk -F'\t' '{n=$1; sub("^/conduit/","",n); print toupper(n)"="$2}'; echo "IMAGE_TAG=$TAG"; } > .env.new
mv .env.new .env; chmod 600 .env
dc() { docker compose -f docker-compose.prod.yml --env-file .env "$@"; }
# shellcheck disable=SC1091
. ./.env
[ -n "${GHCR_TOKEN:-}" ] && echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_OWNER}" --password-stdin >/dev/null

ready() {   # is gateway $1 ready (can it reach Redis and Postgres)? try for up to 60s
  for _ in $(seq 30); do
    dc exec -T "$1" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/readyz', timeout=3)" 2>/dev/null && return 0
    sleep 2
  done
  return 1
}
rollback() {
  echo "!! health check failed, rolling back to ${PREV:-<nothing>}" >&2
  if [ -n "$PREV" ]; then sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$PREV/" .env; dc up -d --no-deps gateway-1 gateway-2 worker dispatcher web mock-a mock-b; dc exec -T nginx nginx -s reload || true; fi
  exit 1
}

# 2. pull new images first (the running containers are untouched while this happens)
dc pull || { echo "pull failed" >&2; exit 1; }
# 3. infrastructure (no-op if already running)
dc up -d postgres redis rabbitmq mock-a mock-b
# 4. migrations: the schema is idempotent (CREATE ... IF NOT EXISTS), run it once with the NEW image before any replica switches
dc run --rm --no-deps gateway-1 python -c "from app import db; db.init(); print('migrations ok')" || rollback
# 5. rolling restart: one gateway at a time; the other keeps serving through NGINX
for gw in gateway-1 gateway-2; do
  dc up -d --no-deps --force-recreate "$gw"
  ready "$gw" || rollback
  dc up -d nginx; dc exec -T nginx nginx -s reload     # nginx re-reads the new container IP
done
# 6. the rest
dc up -d --no-deps worker dispatcher web mock-a mock-b
dc up -d nginx
echo "$PREV" > .prev_tag; echo "$TAG" > .current_tag
docker image prune -f --filter "until=72h" >/dev/null
echo "deployed $TAG (previous: ${PREV:-none})"
