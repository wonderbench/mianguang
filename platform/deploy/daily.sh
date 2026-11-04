#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
    echo "Usage: $0 REMOTE_MOUNT_DIRECTORY AGE_RECIPIENTS_FILE" >&2
    exit 2
fi
deploy_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$deploy_dir"
docker compose exec -T app python manage.py purge_expired
exec "$deploy_dir/backup.sh" "$@"
