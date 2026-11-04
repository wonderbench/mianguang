#!/usr/bin/env bash
# CI-only synthetic deployment/restore smoke; no production configuration is read.
set -euo pipefail
umask 077
deploy_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
temporary=$(mktemp -d)
restore_name=""
export COMPOSE_PROJECT_NAME="mianguang-smoke-${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}"
cleanup() {
    status=$?
    set +e
    if [[ -f "$temporary/compose.json" ]]; then
        if (( status )); then docker compose -f "$temporary/compose.json" logs --no-color --tail 50; fi
        docker compose -f "$temporary/compose.json" down --volumes --remove-orphans
    fi
    if [[ -n "$restore_name" ]]; then docker rm -f "$restore_name"; docker volume rm "$restore_name"; fi
    if mountpoint -q "$temporary/backups"; then sudo umount "$temporary/backups"; fi
    rm -rf -- "$temporary"
    exit "$status"
}
trap cleanup EXIT
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_ADMIN_PASSWORD=$(openssl rand -hex 32)
PGPASSWORD=$(openssl rand -hex 32)
export DJANGO_SECRET_KEY POSTGRES_ADMIN_PASSWORD PGPASSWORD
export DJANGO_ALLOWED_HOSTS=localhost,nginx DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost,https://nginx
export PGUSER=mianguang PGDATABASE=mianguang
mkdir "$temporary/tls" "$temporary/backups"
openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj /CN=localhost \
    -addext 'subjectAltName=DNS:localhost,DNS:nginx' \
    -keyout "$temporary/tls/privkey.pem" -out "$temporary/tls/fullchain.pem" >/dev/null 2>&1
chmod 644 "$temporary/tls/fullchain.pem"
printf 'allow all;\n' > "$temporary/staff-networks.conf"
docker compose --env-file /dev/null -f "$deploy_dir/compose.yaml" config --format json > "$temporary/base.json"
python3 - "$temporary" <<'PY'
import json, pathlib, sys
directory = pathlib.Path(sys.argv[1])
config = json.loads((directory / "base.json").read_text())
nginx = config["services"]["nginx"]
nginx["ports"] = [{"target": 443, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}]
for volume in nginx["volumes"]:
    if volume["target"] == "/etc/nginx/tls":
        volume["source"] = str(directory / "tls")
    if volume["target"] == "/etc/nginx/staff-networks.conf":
        volume["source"] = str(directory / "staff-networks.conf")
(directory / "compose.json").write_text(json.dumps(config))
PY
export COMPOSE_FILE="$temporary/compose.json"
docker compose config --quiet
docker compose build app
docker compose up -d db
docker compose run --rm app python manage.py migrate --noinput
docker compose run --rm app python manage.py init_roles
docker compose run --rm app python manage.py collectstatic --noinput
docker compose run --rm app python manage.py check --deploy
docker compose up -d --wait
docker compose exec -T nginx nginx -t
port=$(docker compose port nginx 443)
base_url="https://localhost:${port##*:}"
expect_status() {
    local expected=$1 path=$2 actual
    shift 2
    actual=$(curl --silent --show-error --cacert "$temporary/tls/fullchain.pem" \
        --output /dev/null --write-out '%{http_code}' "$base_url$path" "$@")
    [[ "$actual" == "$expected" ]] || { echo "$path: expected $expected, got $actual" >&2; return 1; }
}
expect_status 200 /login/
expect_status 404 /healthz
docker compose exec -T app python manage.py shell -c \
    'import secrets; from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser("ci", password=secrets.token_urlsafe(32))'
docker cp "$temporary/tls/fullchain.pem" "$(docker compose ps -q app):/tmp/ci-ca.pem"
docker compose exec -T -e DEMO_MODE=true -e SSL_CERT_FILE=/tmp/ci-ca.pem app \
    python manage.py simulate_devices --actor ci --url https://nginx --count 3 --duration 20
printf 'deny all;\n' > "$temporary/staff-networks.conf"
docker compose exec -T nginx nginx -s reload
sleep 1
expect_status 403 /login/
expect_status 401 /api/device/v1/telemetry -X POST -H 'Content-Type: application/json' --data '{}'
expect_status 404 /healthz

# Local CI mount is a fixture for the backup mount check, not an off-host backup.
sudo mount -t tmpfs -o "size=64m,mode=0700,uid=$(id -u),gid=$(id -g)" tmpfs "$temporary/backups"
age-keygen -o "$temporary/identity.txt" 2>/dev/null
age-keygen -y "$temporary/identity.txt" > "$temporary/recipients.txt"
"$deploy_dir/daily.sh" "$temporary/backups" "$temporary/recipients.txt"
backup=$(find "$temporary/backups" -name '*.dump.age' -print -quit)
"$deploy_dir/restore.sh" "$backup" "$temporary/identity.txt" > "$temporary/restore.log"
cat "$temporary/restore.log"
restore_name=$(awk '/^Isolated restore complete: / {print $4}' "$temporary/restore.log")
restored=$(docker exec "$restore_name" psql -U postgres -d mianguang_restore -Atc \
    "SELECT EXISTS (SELECT 1 FROM auth_user WHERE username='ci') AND (SELECT count(*) FROM monitoring_binding)=3 AND (SELECT count(DISTINCT device_id) FROM monitoring_observation)=3")
[[ "$restored" == t ]]
echo 'PASS: synthetic HTTPS ingestion, personnel boundary, cleanup, encrypted backup and isolated restore.'
