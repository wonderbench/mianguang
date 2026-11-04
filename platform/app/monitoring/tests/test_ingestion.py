import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from monitoring.models import Bed, Binding, Device, Observation, Site
from monitoring.services.bindings import disable_device, register_device, replace_binding, rotate_credential
from monitoring.services.errors import PlatformError
from monitoring.services.ingestion import ingest_telemetry, parse_payload


class IngestionTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser("admin", password="test")
        self.device, self.token = register_device(actor=self.actor, display_code="A")
        self.now = timezone.now().replace(microsecond=0)
        self.payload = json.loads((Path(__file__).resolve().parents[3] / "examples/telemetry.synthetic.valid.json").read_text())
        self.payload.update(device_id=str(self.device.pk), binding_id=None, boot_id=1, seq=0,
                            captured_at=self.now.isoformat().replace("+00:00", "Z"))

    def ingest(self, payload=None, token=None, now=None):
        with patch("monitoring.services.ingestion.timezone.now", return_value=now or self.now):
            return ingest_telemetry(token=token or self.token, body=json.dumps(payload or self.payload).encode())

    def reject(self, code, **kwargs):
        with self.assertRaises(PlatformError) as caught:
            self.ingest(**kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_replay_order_and_reboot(self):
        self.assertEqual(self.ingest()["status"], "accepted")
        self.device.refresh_from_db()
        original_fresh = self.device.last_fresh_received_at
        self.assertEqual(self.ingest(now=self.now + timedelta(minutes=1))["status"], "duplicate")
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_fresh_received_at, original_fresh)
        changed = copy.deepcopy(self.payload)
        changed["sample"]["lamp"]["pwm"] = 1
        self.reject("duplicate_conflict", payload=changed)
        newer = dict(self.payload, seq=1, uptime_ms=self.payload["uptime_ms"] + 1000,
                     captured_at=(self.now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))
        self.assertEqual(self.ingest(newer)["status"], "accepted")
        self.reject("out_of_order", payload=dict(newer, seq=2))
        reboot = dict(newer, boot_id=2, seq=0, uptime_ms=1000,
                      captured_at=(self.now + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"))
        self.assertEqual(self.ingest(reboot)["status"], "accepted")
        self.reject("out_of_order", payload=dict(reboot, boot_id=1, seq=100))
        self.reject("clock_out_of_window", payload=dict(reboot, seq=1), now=self.now + timedelta(seconds=30))
        self.assertEqual(Observation.objects.count(), 3)

    def test_wire_parser_and_quality(self):
        encoded = json.dumps(self.payload)
        cases = [(encoded.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), "malformed_json"),
                 (encoded.replace('"seq": 0', '"seq": NaN'), "malformed_json"),
                 (encoded.replace('"seq": 0', '"seq": 1e999'), "malformed_json"),
                 (encoded + " " * 4096, "payload_too_large"),
                 (json.dumps(dict(self.payload, unexpected=True)), "schema_invalid")]
        for body, code in cases:
            with self.subTest(code=code), self.assertRaises(PlatformError) as caught:
                parse_payload(body.encode())
            self.assertEqual(caught.exception.code, code)
        invalid = copy.deepcopy(self.payload)
        invalid["uptime_ms"] = 100
        self.reject("quality_conflict", payload=invalid)
        invalid = copy.deepcopy(self.payload)
        invalid["sample"]["presence"]["raw"] = 0
        for name in ("rr", "hr"):
            invalid["sample"][name].update(valid=False, reason="conflicting_occupancy")
        self.reject("quality_conflict", payload=invalid)
        response = self.client.post("/api/device/v1/telemetry", data=encoded, content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get("/api/device/v1/telemetry").status_code, 405)

    def test_binding_lifecycle_and_identity(self):
        self.ingest()
        site = Site.objects.create(name="一号楼")
        bed = Bed.objects.create(site=site, room_label="101", bed_label="1")
        binding, token = replace_binding(actor=self.actor, device_id=self.device.pk, bed_id=bed.pk, resident_alias="R1")
        self.device.refresh_from_db()
        self.assertIsNone(self.device.latest_observation_id)
        self.assertEqual(self.device.last_boot_id, 1)
        self.reject("invalid_credential")
        self.reject("binding_mismatch", token=token)
        data = dict(self.payload, binding_id=str(binding.pk), boot_id=2, seq=0, uptime_ms=1000,
                    captured_at=binding.started_at.isoformat().replace("+00:00", "Z"))
        self.reject("binding_not_ready", token=token, payload=data, now=binding.started_at)
        ready = binding.started_at + timedelta(seconds=5)
        data["captured_at"] = ready.isoformat().replace("+00:00", "Z")
        self.assertEqual(self.ingest(data, token=token, now=ready)["status"], "accepted")
        other, _ = register_device(actor=self.actor, display_code="B")
        self.reject("device_identity_mismatch", payload=dict(data, device_id=str(other.pk)), token=token)
        _, diagnostic_token = replace_binding(actor=self.actor, device_id=self.device.pk)
        binding.refresh_from_db()
        self.assertIsNotNone(binding.ended_at)
        self.reject("binding_mismatch", payload=data, token=diagnostic_token)
        disable_device(actor=self.actor, device_id=self.device.pk)
        self.reject("invalid_credential", token=diagnostic_token)
        viewer = get_user_model().objects.create_user("viewer")
        with self.assertRaises(PermissionDenied):
            rotate_credential(actor=viewer, device_id=self.device.pk)

    def test_two_administrators_cannot_assign_same_bed(self):
        other, _ = register_device(actor=self.actor, display_code="B")
        site = Site.objects.create(name="地点")
        bed = Bed.objects.create(site=site, room_label="房间", bed_label="床位")
        barrier = threading.Barrier(2)

        def bind(device_id):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                replace_binding(actor=actor, device_id=device_id, bed_id=bed.pk, resident_alias="R")
                return "ok"
            except PlatformError as exc:
                return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(bind, [self.device.pk, other.pk]))
        self.assertCountEqual(results, ["ok", "bed_occupied"])
        self.assertEqual(Binding.objects.filter(ended_at__isnull=True).count(), 1)

    def test_rotation_rejects_request_already_waiting_for_device_lock(self):
        parsed = threading.Event()

        def parse(body):
            result = parse_payload(body)
            parsed.set()
            return result

        def send():
            close_old_connections()
            try:
                self.ingest()
                return "accepted"
            except PlatformError as exc:
                return exc.code
            finally:
                close_old_connections()

        with patch("monitoring.services.ingestion.parse_payload", side_effect=parse), ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Device.objects.select_for_update().get(pk=self.device.pk)
                pending = pool.submit(send)
                self.assertTrue(parsed.wait(timeout=10))
                rotate_credential(actor=self.actor, device_id=self.device.pk)
            self.assertEqual(pending.result(timeout=10), "invalid_credential")
        self.assertFalse(Observation.objects.exists())
