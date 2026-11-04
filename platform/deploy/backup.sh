#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# != 2 ]]; then
    echo "Usage: $0 REMOTE_MOUNT_DIRECTORY AGE_RECIPIENTS_FILE" >&2
    exit 2
fi
deploy_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
backup_dir=$(realpath -- "$1")
recipients=$(realpath -- "$2")
# Refuse to write into an unmounted local fallback after a remote mount fails.
mountpoint -q -- "$backup_dir"
cd -- "$deploy_dir"
filename="mianguang-$(date -u +%F).dump.age"
temporary=$(mktemp "$backup_dir/.mianguang-XXXXXX")
trap 'rm -f -- "$temporary" "$temporary.sha256"' EXIT

docker compose exec -T db sh -c \
    'exec pg_dump --username="$PGUSER" --dbname="$PGDATABASE" --format=custom --no-owner --no-acl' \
    | age --recipients-file "$recipients" > "$temporary"
test -s "$temporary"
digest=$(sha256sum -- "$temporary")
printf '%s  %s\n' "${digest%% *}" "$filename" > "$temporary.sha256"
mv -- "$temporary" "$backup_dir/$filename"
mv -- "$temporary.sha256" "$backup_dir/$filename.sha256"
(cd -- "$backup_dir" && sha256sum --check "$filename.sha256")

# One file per UTC day; rerunning replaces that day's file only after success.
while IFS= read -r expired; do
    rm -- "$backup_dir/$expired" "$backup_dir/$expired.sha256"
done < <(find "$backup_dir" -maxdepth 1 -type f -name 'mianguang-????-??-??.dump.age' -printf '%f\n' | LC_ALL=C sort -r | tail -n +8)
printf 'Encrypted backup complete: %s (%s bytes)\n' "$filename" "$(stat -c %s "$backup_dir/$filename")"
