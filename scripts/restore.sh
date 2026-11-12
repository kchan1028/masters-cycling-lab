#!/usr/bin/env bash
# Replace the stack's database and uploaded PDFs with a backup: make restore BACKUP=backups/<time>
#
# Everything currently stored is replaced: documents, index versions, answers and evaluation runs. The database
# container must be running. API and worker are stopped during the restore and started again afterwards.
set -euo pipefail

cd "$(dirname "$0")/.."
dir=${1:-}
if [ -z "$dir" ] || [ ! -f "$dir/database.dump" ] || [ ! -f "$dir/storage.tar" ]; then
  echo "Usage: make restore BACKUP=backups/<time> (a folder made by make backup)" >&2
  exit 1
fi
(cd "$dir" && shasum -a 256 --check --quiet SHA256SUMS) || { echo "$dir does not match its SHA256SUMS." >&2; exit 1; }

read -r -p "This replaces ALL current data with $dir. Type 'restore' to continue: " answer
if [ "$answer" != restore ]; then
  echo "Nothing changed."
  exit 1
fi

docker compose stop api worker
# A fresh database rather than pg_restore --clean, so nothing from the current data survives.
docker compose exec -T db dropdb --username mcl --force mcl
docker compose exec -T db createdb --username mcl mcl
docker compose exec -T db pg_restore --username mcl --dbname mcl --exit-on-error < "$dir/database.dump"
docker compose run --rm --no-deps -T worker \
  sh -c 'find /data/storage -mindepth 1 -delete && tar -C /data/storage -xf -' < "$dir/storage.tar"
docker compose start api worker
echo "Restored $dir. Check http://127.0.0.1:8080/api/v1/health/ready"
