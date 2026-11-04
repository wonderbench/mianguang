"""Synthetic PostgreSQL/HTTP capacity exercise for a dedicated demo deployment."""
import importlib
import json
import math
import os
import platform
import re
import ssl
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.utils import timezone

from monitoring.models import Bed, Binding, Device, Observation, Site
from monitoring.services.bindings import disable_device, register_device, replace_binding, require_manager

FULL_ROWS = 6048000
INTERVAL = 10
VIEW_INTERVAL = 15
TIMING = re.compile(r"(?:^|,)\s*app\s*;\s*dur=([0-9.]+)")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, *args, **kwargs):
        return None


def percentile(histogram):
    rank = math.ceil(sum(histogram.values()) * .95)
    total = 0
    for value, count in sorted(histogram.items()):
        total += count
        if total >= rank:
            return value
    return None


class Measurements:
    def __init__(self, tls_context):
        self.tls_context = tls_context
        self.lock = threading.Lock()
        self.rows = defaultdict(lambda: {"statuses": Counter(), "errors": Counter(), "client_ms": Counter(), "server_ms": Counter(), "bytes": 0})
        self.sessions_created = 0
        self.session_renewals = 0
        self.missed_schedules = Counter()

    def request(self, kind, request, expected=None):
        started = time.monotonic()
        status, headers, content, error = 0, {}, b"", None
        try:
            opener = build_opener(NoRedirect(), HTTPSHandler(context=self.tls_context))
            try:
                response = opener.open(request, timeout=5 if kind in ("burst", "telemetry") else 30)
            except HTTPError as exc:
                response = exc
            with response:
                status, headers, content = response.status, response.headers, response.read()
            if status != 200:
                error = f"http_{status}"
            elif expected:
                result = json.loads(content)
                if any(result.get(key) != value for key, value in expected.items()):
                    error = "unexpected_response"
        except (URLError, OSError, ValueError) as exc:
            error = type(exc).__name__
        elapsed = (time.monotonic() - started) * 1000
        timing = TIMING.search(headers.get("Server-Timing", ""))
        with self.lock:
            row = self.rows[kind]
            row["statuses"][str(status)] += 1
            row["client_ms"][math.ceil(elapsed)] += 1
            row["bytes"] += len(content)
            if timing:
                row["server_ms"][math.ceil(float(timing.group(1)))] += 1
            if error:
                row["errors"][error] += 1
        return error is None

    def report(self):
        return {kind: {
            "requests": sum(row["statuses"].values()), "status_counts": dict(row["statuses"]),
            "errors": dict(row["errors"]), "response_bytes": row["bytes"],
            "client_p95_ms": percentile(row["client_ms"]),
            "app_p95_ms": percentile(row["server_ms"]),
            "app_timed_requests": sum(row["server_ms"].values()),
        } for kind, row in self.rows.items()}


class SessionClient:
    """Standard Django sessions, created locally; no browser/login claim is made."""
    def __init__(self, user, measurements):
        self.user = user
        self.measurements = measurements
        self.session = None
        self.created_at = 0

    def cookie(self):
        if self.session is None or time.monotonic() - self.created_at >= min(21600, settings.SESSION_COOKIE_AGE / 2):
            close_old_connections()
            previous = self.session
            session = importlib.import_module(settings.SESSION_ENGINE).SessionStore()
            session[SESSION_KEY] = str(self.user.pk)
            session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
            session[HASH_SESSION_KEY] = self.user.get_session_auth_hash()
            session.set_expiry(settings.SESSION_COOKIE_AGE)
            session.save()
            self.session, self.created_at = session, time.monotonic()
            if previous:
                previous.delete()
            with self.measurements.lock:
                self.measurements.sessions_created += 1
                self.measurements.session_renewals += previous is not None
            close_old_connections()
        return f"{settings.SESSION_COOKIE_NAME}={self.session.session_key}"

    def close(self):
        if self.session:
            close_old_connections()
            self.session.delete()
            close_old_connections()


def database_size():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database()), pg_total_relation_size('monitoring_observation'), current_setting('server_version')")
        size, observations, postgres_version = cursor.fetchone()
    return {"database_bytes": size, "observations_bytes": observations, "postgres_version": postgres_version}


def machine_info():
    result = {"os": platform.system(), "kernel": platform.release(), "architecture": platform.machine(),
              "python": platform.python_version(), "cpu_count": os.cpu_count(),
              "host_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
              "django": version("Django"), "psycopg": version("psycopg")}
    for label, filename in (("cgroup_cpu_max", "/sys/fs/cgroup/cpu.max"), ("cgroup_memory_max", "/sys/fs/cgroup/memory.max")):
        path = Path(filename)
        if path.is_file():
            result[label] = path.read_text().strip()
    return result


def seed_history(devices, rows, sample, anchor):
    """One bounded PostgreSQL INSERT per device; payloads retain the full contract."""
    inserted = 0
    sample_json = json.dumps(sample, sort_keys=True, separators=(",", ":"))
    for index, (device, binding, _) in enumerate(devices):
        count = rows // len(devices) + (index < rows % len(devices))
        if not count:
            continue
        start = anchor - timedelta(seconds=count * INTERVAL)
        Binding.objects.filter(pk=binding.pk).update(started_at=start - timedelta(seconds=5))
        # Alphabetical keys and compact JSON match the ingestion canonical hash.
        prefix = '{"binding_id":"' + str(binding.pk) + '","boot_id":1,"captured_at":"'
        middle = '","device_id":"' + str(device.pk) + '","firmware_version":"benchmark-v1","sample":' + sample_json + ',"schema_version":1,"seq":'
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO monitoring_observation
                  (device_id, binding_id, boot_id, seq, captured_at, received_at,
                   uptime_ms, firmware_version, payload, payload_hash)
                SELECT %s, %s, 1, seq, captured, captured, seq * 10000 + 1000,
                       'benchmark-v1', body::jsonb, encode(sha256(convert_to(body, 'UTF8')), 'hex')
                FROM (
                  SELECT seq, captured,
                    %s || to_char(captured AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') ||
                    %s || seq::text || ',"uptime_ms":' || (seq * 10000 + 1000)::text || '}' AS body
                  FROM (SELECT seq, %s::timestamptz + seq * interval '10 seconds' AS captured
                        FROM generate_series(0, %s - 1) AS seq) AS times
                ) AS packets
            """, [device.pk, binding.pk, prefix, middle, start, count])
            inserted += cursor.rowcount
        latest = Observation.objects.filter(device=device, boot_id=1).order_by("-seq").first()
        Device.objects.filter(pk=device.pk).update(latest_observation=latest, last_boot_id=1,
            last_seq=latest.seq, last_uptime_ms=latest.uptime_ms, last_captured_at=latest.captured_at,
            last_fresh_received_at=latest.received_at)
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE monitoring_observation")
    return inserted


def wait_until(deadline):
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


class Command(BaseCommand):
    help = "专用演示部署的真实HTTP会话/设备负载与合成历史容量验收；不会冒充真机或24小时结果。"

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--devices", type=int, default=100)
        parser.add_argument("--viewers", type=int, default=10)
        parser.add_argument("--duration", type=int, default=60, help="持续混合负载秒数；完整验收使用86400")
        parser.add_argument("--seed-rows", type=int, default=0, help="本次新建设备的完整合成历史行数；目标6048000")
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA"))
        parser.add_argument("--ca-file")
        parser.add_argument("--allow-local-http", action="store_true")
        parser.add_argument("--require-full", action="store_true", help="不足100台/10会话/24小时/6048000行或性能目标不通过时退出2")

    def handle(self, *args, **options):
        if not settings.DEMO_MODE or connection.vendor != "postgresql":
            raise CommandError("只允许DEMO_MODE=true的专用PostgreSQL演示部署。")
        if Device.objects.filter(is_simulator=False).exists():
            raise CommandError("演示库中存在真实设备；请使用独立数据库。")
        count, viewers, duration, rows = (options[key] for key in ("devices", "viewers", "duration", "seed_rows"))
        if not (1 <= count <= 100 and 1 <= viewers <= 10 and 15 <= duration <= 86400 and 0 <= rows <= count * 60480):
            raise CommandError("设备1–100、会话1–10、时长15–86400秒；历史每设备最多60480条（7天）。")
        url = options["url"].rstrip("/")
        parsed = urlparse(url)
        local_http = options["allow_local_http"] and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CommandError("需要HTTPS根地址；显式本地HTTP只接受回环主机，地址不得含凭证或查询串。")
        actor = get_user_model().objects.get(username=options["actor"])
        require_manager(actor)
        viewer_group = Group.objects.get(name="查看员")
        metrics = Measurements(ssl.create_default_context(cafile=options["ca_file"]))
        run = uuid.uuid4().hex[:12]
        before = database_size()
        sample = json.loads((Path(__file__).resolve().parents[4] / "examples/telemetry.synthetic.valid.json").read_text())["sample"]
        devices, users = [], []
        with transaction.atomic():
            site = Site.objects.create(name=f"容量模拟 {run}")
            for index in range(count):
                bed = Bed.objects.create(site=site, room_label="模拟", bed_label=str(index + 1))
                device, _ = register_device(actor=actor, display_code=f"BENCH-{run}-{index + 1}", is_simulator=True)
                binding, token = replace_binding(actor=actor, device_id=device.pk, bed_id=bed.pk, resident_alias=f"模拟-{index + 1}")
                devices.append((device, binding, token))
            for index in range(viewers):
                user = get_user_model().objects.create_user(f"bench-{run}-{index + 1}")
                user.groups.add(viewer_group)
                users.append(user)
        cleanup_ok = True
        try:
            seed_started = time.monotonic()
            inserted = seed_history(devices, rows, sample, timezone.now().replace(second=0, microsecond=0)) if rows else 0
            seed_seconds = time.monotonic() - seed_started
            after_seed = database_size()
            self.stderr.write(f"run={run} synthetic_devices={count} seeded_rows={inserted}; starting HTTP load")
            wait_until(time.monotonic() + max(0, 5 - seed_seconds))
            boot_started = time.monotonic()
            sequences = [0] * count
            accepted = Counter()

            def send_device(index, kind):
                device, binding, token = devices[index]
                seq = sequences[index]
                sequences[index] += 1
                payload = {"schema_version": 1, "device_id": str(device.pk), "binding_id": str(binding.pk),
                    "boot_id": 2, "seq": seq, "captured_at": timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "uptime_ms": 1000 + int((time.monotonic() - boot_started) * 1000), "firmware_version": "benchmark-v1", "sample": sample}
                request = Request(url + "/api/device/v1/telemetry", data=json.dumps(payload).encode(), method="POST",
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
                if metrics.request(kind, request, {"status": "accepted", "boot_id": 2, "seq": seq}):
                    with metrics.lock:
                        accepted[index] += 1

            burst_start = time.monotonic() + 1
            def burst(index):
                wait_until(burst_start)
                send_device(index, "burst")
            with ThreadPoolExecutor(max_workers=count) as pool:
                list(pool.map(burst, range(count)))

            start = time.monotonic() + 1
            end = start + duration
            stop = threading.Event()
            def periodic(kind, interval, phase, callback):
                scheduled = start + phase
                while scheduled < end:
                    if stop.wait(max(0, scheduled - time.monotonic())):
                        break
                    if time.monotonic() >= end:
                        with metrics.lock:
                            metrics.missed_schedules[kind] += math.ceil((end - scheduled) / interval)
                        break
                    callback()
                    scheduled += interval
                    if scheduled < end and time.monotonic() > scheduled:
                        missed = min(int((time.monotonic() - scheduled) // interval) + 1, math.ceil((end - scheduled) / interval))
                        with metrics.lock:
                            metrics.missed_schedules[kind] += missed
                        scheduled += missed * interval

            def view(index):
                session = SessionClient(users[index], metrics)
                try:
                    periodic("overview", VIEW_INTERVAL, index * VIEW_INTERVAL / viewers, lambda: metrics.request("overview",
                        Request(url + f"/fragments/overview/?site={site.pk}", headers={"Cookie": session.cookie()})))
                finally:
                    session.close()

            def query_history():
                session = SessionClient(actor, metrics)
                binding = devices[0][1]
                def query():
                    to_time = timezone.now().replace(second=0, microsecond=0)
                    params = urlencode({"from": (to_time - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
                                        "to": to_time.isoformat().replace("+00:00", "Z")})
                    for kind, path in (("series", f"/api/ui/v1/bindings/{binding.pk}/series"), ("csv", f"/bindings/{binding.pk}/export.csv")):
                        metrics.request(kind, Request(url + path + "?" + params, headers={"Cookie": session.cookie()}))
                try:
                    periodic("history", VIEW_INTERVAL, 0, query)
                finally:
                    session.close()

            started_at = timezone.now()
            with ThreadPoolExecutor(max_workers=count + viewers + 1) as pool:
                futures = [pool.submit(periodic, "telemetry", INTERVAL, index * INTERVAL / count,
                                       lambda index=index: send_device(index, "telemetry")) for index in range(count)]
                futures += [pool.submit(view, index) for index in range(viewers)]
                futures.append(pool.submit(query_history))
                try:
                    done, _ = wait(futures, return_when=FIRST_EXCEPTION)
                    for future in done:
                        future.result()
                    wait_until(end)
                except BaseException:
                    stop.set()
                    raise
            elapsed = time.monotonic() - start
            device_ids = [device.pk for device, _, _ in devices]
            actual_rows = Observation.objects.filter(device_id__in=device_ids).count()
            watermarks_ok = all(device.latest_observation and
                (device.last_boot_id, device.last_seq, device.last_uptime_ms, device.last_captured_at) ==
                (device.latest_observation.boot_id, device.latest_observation.seq, device.latest_observation.uptime_ms, device.latest_observation.captured_at)
                for device in Device.objects.filter(pk__in=device_ids).select_related("latest_observation"))
            results = metrics.report()
            expected_requests = {
                "burst": count,
                "telemetry": sum(math.ceil((duration - index * INTERVAL / count) / INTERVAL) for index in range(count)),
                "overview": sum(math.ceil((duration - index * VIEW_INTERVAL / viewers) / VIEW_INTERVAL) for index in range(viewers)),
                "series": math.ceil(duration / VIEW_INTERVAL), "csv": math.ceil(duration / VIEW_INTERVAL),
            }
            thresholds = {kind: results.get(kind, {}).get("app_p95_ms") is not None and results[kind]["app_p95_ms"] <= limit
                          for kind, limit in (("telemetry", 500), ("overview", 1000), ("series", 2000), ("csv", 2000))}
            checks = {"all_http_requests_succeeded": all(not row["errors"] for row in results.values()),
                "server_timing_complete": all(row["app_timed_requests"] == row["requests"] for row in results.values()),
                "each_device_accepted": len(accepted) == count,
                "scheduled_requests_completed": all(results.get(kind, {}).get("requests") == expected for kind, expected in expected_requests.items()),
                "stored_row_count_matches": actual_rows == inserted + sum(accepted.values()),
                "watermarks_match_latest": watermarks_ok, "no_missed_schedules": not metrics.missed_schedules}
            full_scope = count == 100 and viewers == 10 and elapsed >= 86400 and inserted >= FULL_ROWS
            full_passed = full_scope and all(checks.values()) and all(thresholds.values())
            report = {"schema_version": 1, "synthetic": True, "run_id": run, "revision": options["revision"],
                "started_at": started_at.isoformat(), "finished_at": timezone.now().isoformat(),
                "load_duration_seconds": round(elapsed, 3), "requested_duration_seconds": duration,
                "devices": count, "viewer_sessions": viewers, "device_interval_seconds": INTERVAL, "viewer_interval_seconds": VIEW_INTERVAL,
                "burst_devices": count, "history_seed_rows": inserted, "history_seed_seconds": round(seed_seconds, 3),
                "run_observation_rows": actual_rows, "live_accepted": sum(accepted.values()),
                "session_source": "local Django SessionStore; HTTP session polling, no HTTP login or browser rendering",
                "http_logins": 0, "sessions_created": metrics.sessions_created, "session_renewals": metrics.session_renewals,
                "latency_scope": "app is Django Server-Timing, excludes proxy queue/network; client includes TLS/network/body transfer",
                "p95_resolution_ms": 1, "measurements": results, "expected_requests": expected_requests,
                "missed_schedules": dict(metrics.missed_schedules),
                "checks": checks, "observed_app_thresholds": thresholds, "full_capacity_scope": full_scope,
                "full_capacity_passed": full_passed, "result": "full_capacity_passed" if full_passed else "smoke_passed" if all(checks.values()) else "failed",
                "machine": machine_info(), "database_before": before, "database_after_seed": after_seed, "database_after_load": database_size(),
                "not_verified": ["physical devices and UART/lamp behavior", "real browser rendering", "institution network and off-host recovery"] +
                    ([] if full_scope else ["100 devices, 10 sessions, 24 hours and 6048000 historical rows together"])}
        finally:
            close_old_connections()
            try:
                for device, _, _ in devices:
                    disable_device(actor=actor, device_id=device.pk)
                get_user_model().objects.filter(pk__in=[user.pk for user in users]).update(is_active=False)
            except DatabaseError:
                cleanup_ok = False
                self.stderr.write("数据库不可写，本批设备/账号清理未完成；恢复后重建此独立演示库。")
        checks["cleanup_completed"] = cleanup_ok
        if not cleanup_ok:
            report["full_capacity_passed"] = False
            report["result"] = "failed"
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not all(checks.values()):
            raise CommandError("负载中出现失败或一致性问题；查看JSON报告。")
        if options["require_full"] and not full_passed:
            raise CommandError("本次未达到完整容量验收范围或性能目标；短跑不能替代24小时结果。", returncode=2)
