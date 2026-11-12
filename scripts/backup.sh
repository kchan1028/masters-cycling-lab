#!/usr/bin/env bash
# Back up the running stack's database and uploaded PDFs: make backup
#
# Writes backups/<UTC time>/ with database.dump (pg_dump custom format), storage.tar and SHA256SUMS. The embedding
# model is not included; `make download-model` fetches it again. The two parts are copied one after the other, so
# take a backup while nothing is being uploaded or deleted.
set -euo pipefail

cd "$(dirname "$0")/.."
dir="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$dir"
trap 'echo "Backup failed; removing $dir" >&2; rm -rf "$dir"' ERR

docker compose exec -T db pg_dump --username mcl --dbname mcl --format custom > "$dir/database.dump"
docker compose exec -T api tar -C /data/storage -cf - . > "$dir/storage.tar"

# A backup that cannot be read back is not a backup.
docker compose exec -T db pg_restore --list < "$dir/database.dump" > /dev/null
tar -tf "$dir/storage.tar" > /dev/null
(cd "$dir" && shasum -a 256 database.dump storage.tar > SHA256SUMS)

documents=$(docker compose exec -T db psql --username mcl --dbname mcl --tuples-only --no-align \
  --command "select count(*) from documents where deleted_at is null" || echo "?")
echo "Backed up $documents documents to $dir ($(du -sh "$dir" | cut -f1))."
