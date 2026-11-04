import json
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from monitoring.models import Bed, Site
from monitoring.services.bindings import register_device, replace_binding


class Command(BaseCommand):
    help = "在专用演示部署新登记模拟设备，通过HTTP入口每10秒发送当前快照。"

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--count", type=int, default=3)
        parser.add_argument("--duration", type=int, default=60)
        parser.add_argument("--allow-local-http", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("模拟器只能在 DEMO_MODE=true 的专用演示部署运行。")
        url = options["url"].rstrip("/")
        parsed = urlparse(url)
        local_http = options["allow_local_http"] and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
        if parsed.scheme != "https" and not local_http:
            raise CommandError("需要HTTPS；本地开发需显式 --allow-local-http。")
        if not 1 <= options["count"] <= 100 or options["duration"] < 10:
            raise CommandError("设备数1–100，运行时长至少10秒。")
        try:
            actor = get_user_model().objects.get(username=options["actor"])
        except get_user_model().DoesNotExist:
            raise CommandError("管理员账号不存在。") from None
        sample = json.loads((Path(__file__).resolve().parents[4] / "examples/telemetry.synthetic.valid.json").read_text())["sample"]
        run = uuid.uuid4().hex[:8]
        devices = []
        with transaction.atomic():
            site = Site.objects.create(name=f"模拟演示 {run}")
            for number in range(options["count"]):
                bed = Bed.objects.create(site=site, room_label="模拟房间", bed_label=str(number + 1))
                device, _ = register_device(actor=actor, display_code=f"SIM-{run}-{number + 1}", is_simulator=True)
                binding, token = replace_binding(actor=actor, device_id=device.pk, bed_id=bed.pk, resident_alias=f"模拟-{number + 1}")
                devices.append((str(device.pk), str(binding.pk), token))
        self.stdout.write(f"已登记 {len(devices)} 台模拟设备；等待绑定隔离期。")
        time.sleep(5)

        def send(device):
            device_id, binding_id, token = device
            time.sleep(random.uniform(0, 2))
            started = time.monotonic()
            sequence, failures, accepted, rejected, latencies = 0, 0, 0, 0, []
            while time.monotonic() - started < options["duration"]:
                began = time.monotonic()
                payload = {"schema_version": 1, "device_id": device_id, "binding_id": binding_id,
                    "boot_id": 1, "seq": sequence, "captured_at": timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "uptime_ms": 1000 + int((began - started) * 1000), "firmware_version": "simulator-v1", "sample": sample}
                request = Request(url + "/api/device/v1/telemetry", data=json.dumps(payload).encode(),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
                try:
                    with urlopen(request, timeout=5) as response:
                        result = json.load(response)
                    accepted += result.get("status") == "accepted"
                    failures = 0
                    delay = 10
                except HTTPError as exc:
                    rejected += 1
                    if exc.code in (401, 403, 409):
                        break
                    failures += 1
                    delay = min(30, 2 ** min(failures - 1, 5)) if exc.code == 429 or exc.code >= 500 else 10
                except (URLError, TimeoutError):
                    rejected += 1
                    failures += 1
                    delay = min(30, 2 ** min(failures - 1, 5))
                latencies.append(time.monotonic() - began)
                sequence += 1
                # The next attempt builds a new current sample; there is no offline queue.
                remaining = options["duration"] - (time.monotonic() - started)
                time.sleep(max(0, min(remaining, delay + random.uniform(0, 0.2) - (time.monotonic() - began))))
            return accepted, rejected, latencies

        with ThreadPoolExecutor(max_workers=options["count"]) as pool:
            results = list(pool.map(send, devices))
        timings = sorted(value for _, _, values in results for value in values)
        self.stdout.write(json.dumps({"simulated": True, "devices": len(devices),
            "accepted": sum(row[0] for row in results), "rejected": sum(row[1] for row in results),
            "request_p95_ms": round(timings[min(len(timings) - 1, int(len(timings) * .95))] * 1000, 2) if timings else None}))
        if any(row[1] for row in results):
            raise CommandError("模拟运行存在拒绝/网络失败，请查看接入日志。")
