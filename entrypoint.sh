#!/bin/sh
set -e

echo "PG_DB_HOST=$PG_DB_HOST"
echo "PG_DB_PORT=$PG_DB_PORT"
echo "PG_DB_USER=$PG_DB_USER"
echo "PG_DB_NAME=$PG_DB_NAME"

export PGPASSWORD="$PG_DB_PASSWORD"

echo "Waiting for Postgres at ${PG_DB_HOST}:${PG_DB_PORT}..."

MAX_TRIES=30
TRIES=0

until pg_isready -h "$PG_DB_HOST" -p "$PG_DB_PORT" -U "$PG_DB_USER" > /dev/null 2>&1; do
  TRIES=$((TRIES+1))
  if [ "$TRIES" -ge "$MAX_TRIES" ]; then
    echo "Postgres is still not ready after ${MAX_TRIES} attempts. Exiting."
    exit 1
  fi
  echo "Postgres not ready yet... retry ${TRIES}/${MAX_TRIES}"
  sleep 2
done

echo "Postgres is ready!"

if [ "$#" -eq 0 ]; then
  exec gunicorn apps.app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w 4 \
    -b ${HOST:-0.0.0.0}:${PORT:-8000} \
    --forwarded-allow-ips="*" \
    --access-logfile - \
    --error-logfile -
else
  exec "$@"
fi