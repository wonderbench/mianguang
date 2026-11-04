#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# != 2 ]]; then
    echo "Usage: $0 BACKUP.dump.age AGE_IDENTITY_FILE" >&2
    exit 2
fi
backup=$(realpath -- "$1")
identity=$(realpath -- "$2")
(cd -- "$(dirname -- "$backup")" && sha256sum --check "$(basename -- "$backup").sha256")

# A new isolated container and volume; this script never opens production .env.
restore_name="mianguang-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$"
restore_created=0
cleanup_failed_restore() {
    if (( restore_created )); then
        docker rm -f "$restore_name" >/dev/null
        docker volume rm "$restore_name" >/dev/null
    fi
}
trap cleanup_failed_restore EXIT
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(openssl rand -hex 32)
docker create --name "$restore_name" --network none \
    --mount "type=volume,source=$restore_name,target=/var/lib/postgresql/data" \
    --env POSTGRES_PASSWORD --env POSTGRES_DB=mianguang_restore \
    postgres:17.11-bookworm@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5 >/dev/null
restore_created=1
docker start "$restore_name" >/dev/null
for ((attempt=0; attempt<30; attempt++)); do
    if docker exec "$restore_name" pg_isready -h 127.0.0.1 -U postgres -d mianguang_restore >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec "$restore_name" pg_isready -h 127.0.0.1 -U postgres -d mianguang_restore
age --decrypt --identity "$identity" "$backup" \
    | docker exec -i "$restore_name" pg_restore --username=postgres --dbname=mianguang_restore \
        --no-owner --no-acl --exit-on-error --single-transaction
docker exec -i "$restore_name" psql -U postgres -d mianguang_restore --set ON_ERROR_STOP=1 <<'SQL'
SELECT (SELECT count(*) FROM auth_user) AS accounts,
       (SELECT count(*) FROM monitoring_binding) AS bindings,
       (SELECT count(*) FROM monitoring_observation) AS observations,
       (SELECT count(*) FROM monitoring_device WHERE last_boot_id IS NOT NULL) AS devices_with_watermarks;
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM monitoring_observation o JOIN monitoring_binding b ON b.id = o.binding_id
    WHERE o.device_id <> b.device_id
  ) OR EXISTS (
    SELECT 1 FROM monitoring_device d JOIN monitoring_observation o ON o.id = d.latest_observation_id
    WHERE d.id <> o.device_id OR d.last_boot_id IS DISTINCT FROM o.boot_id
       OR d.last_seq IS DISTINCT FROM o.seq OR d.last_uptime_ms IS DISTINCT FROM o.uptime_ms
       OR d.last_captured_at IS DISTINCT FROM o.captured_at
  ) THEN RAISE EXCEPTION 'Restored binding/latest/watermark mismatch'; END IF;
END $$;
SQL
trap - EXIT
printf 'Isolated restore complete: %s\n' "$restore_name"
printf 'Inspect: docker exec -it %s psql -U postgres -d mianguang_restore\n' "$restore_name"
printf 'After recording the drill, remove its sensitive copy:\ndocker rm -f %s\ndocker volume rm %s\n' "$restore_name" "$restore_name"
