import copy
import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from monitoring.models import AuditEntry, Bed, Binding, Device, Observation, Site
from monitoring.services.bindings import register_device
from monitoring.services.queries import read_binding_history, read_current


class ManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", verbosity=0)
        cls.admin = get_user_model().objects.create_superuser("admin", password="test")
        cls.viewer = get_user_model().objects.create_user("viewer", password="test")
        cls.viewer.groups.add(Group.objects.get(name="查看员"))
        cls.manager = get_user_model().objects.create_user("manager", password="test")
        cls.manager.groups.add(Group.objects.get(name="平台管理员"))
        cls.device, cls.token = register_device(actor=cls.admin, display_code="SIM-1", is_simulator=True)
        cls.site = Site.objects.create(name="A")
        cls.bed = Bed.objects.create(site=cls.site, room_label="1", bed_label="1")
        cls.end = timezone.now().replace(second=0, microsecond=0)
        cls.start = cls.end - timedelta(minutes=10)
        cls.binding = Binding.objects.create(device=cls.device, bed=cls.bed, resident_alias="=R1",
            location_label_snapshot="+Room", started_at=cls.start - timedelta(seconds=5), created_by=cls.admin)
        cls.payload = json.loads((Path(__file__).resolve().parents[3] / "examples/telemetry.synthetic.valid.json").read_text())
        for seq in range(6):
            captured = cls.start + timedelta(seconds=seq * 10)
            Observation.objects.create(device=cls.device, binding=cls.binding, boot_id=1, seq=seq,
                captured_at=captured, received_at=captured, uptime_ms=1000 + seq * 10000,
                firmware_version="simulator", payload=cls.payload, payload_hash=str(seq))

    def range_params(self):
        return {"from": self.start.isoformat().replace("+00:00", "Z"), "to": self.end.isoformat().replace("+00:00", "Z")}

    def test_slots_completeness_and_broken_minutes(self):
        result = read_binding_history(self.binding, self.start, self.end)
        self.assertEqual(result["summary"]["expected_slots"], 60)
        self.assertEqual(result["summary"]["received_slots"], 6)
        self.assertEqual(result["summary"]["report_completeness"], 0.1)
        self.assertEqual(result["summary"]["rr_valid_ratio"], 1)
        self.assertEqual(result["buckets"][0]["rr_bpm"], 16)
        self.assertIsNone(result["buckets"][1]["rr_bpm"])
        self.binding.started_at = self.start + timedelta(seconds=1)
        result = read_binding_history(self.binding, self.start, self.end)
        self.assertEqual(result["summary"]["expected_slots"], 59)
        self.assertEqual(result["summary"]["received_slots"], 5)
        self.assertIsNone(result["buckets"][0]["rr_bpm"])
        self.binding.started_at = self.end
        result = read_binding_history(self.binding, self.start, self.end)
        self.assertIsNone(result["summary"]["report_completeness"])
        self.assertIsNone(result["summary"]["rr_valid_ratio"])

    def test_current_state_at_expiry_and_unknown_occupancy(self):
        observation = Observation.objects.get(device=self.device, seq=0)
        self.device.latest_observation = observation
        self.device.last_fresh_received_at = self.start
        self.binding.device = self.device
        self.assertEqual(read_current(self.binding, self.start + timedelta(seconds=30))["state"], "fresh")
        self.assertEqual(read_current(self.binding, self.start + timedelta(seconds=31))["state"], "expired")
        self.assertIsNone(read_current(self.binding, self.start + timedelta(seconds=31))["rr"])
        self.assertEqual(read_current(self.binding, self.start + timedelta(seconds=60))["state"], "expired")
        self.assertEqual(read_current(self.binding, self.start + timedelta(seconds=61))["state"], "no_report")
        observation.payload = copy.deepcopy(self.payload)
        observation.payload["sample"]["bed"]["valid"] = False
        self.assertEqual(read_current(self.binding, self.start)["occupancy"], "未知")
        self.device.latest_observation = None
        self.assertEqual(read_current(self.binding, self.end)["state"], "no_report")

    def test_viewer_pages_and_export_permissions(self):
        series = f"/api/ui/v1/bindings/{self.binding.pk}/series"
        export = f"/bindings/{self.binding.pk}/export.csv"
        self.assertEqual(self.client.get(series, self.range_params()).status_code, 401)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get(f"/bindings/{self.binding.pk}/").status_code, 200)
        self.assertEqual(self.client.get(series, self.range_params()).status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 403)
        self.assertEqual(self.client.post("/admin/monitoring/device/add/", {"display_code": "invalid"}).status_code, 403)
        self.assertEqual(self.client.get(export, self.range_params()).status_code, 403)
        self.assertEqual(self.client.get(series).status_code, 400)
        params = self.range_params()
        params["from"] = (self.end - timedelta(days=8)).isoformat().replace("+00:00", "Z")
        self.assertEqual(self.client.get(series, params).status_code, 400)
        self.client.force_login(self.admin)
        response = self.client.get(export, self.range_params())
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn("'=R1", text)
        self.assertIn("'+Room", text)
        self.assertIn("is_simulator", text)
        self.assertIn("rr_reason", text)
        self.assertNotIn(self.token, text)
        entry = AuditEntry.objects.latest("pk")
        self.assertEqual(entry.details["row_count"], 6)
        self.assertNotIn("=R1", json.dumps(entry.details))

    def test_admin_credential_once_location_guard_and_account_scope(self):
        self.client.force_login(self.manager)
        response = self.client.post("/admin/monitoring/device/add/", {"display_code": "B", "is_simulator": "on", "_save": "Save"})
        self.assertEqual(response.status_code, 200)
        token = response.context["token"]
        device = Device.objects.get(display_code="B")
        self.assertNotEqual(device.token_hash, token)
        response = self.client.get(f"/admin/monitoring/device/{device.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(token, response.content.decode())
        self.client.post(f"/admin/monitoring/site/{self.site.pk}/change/", {"name": "A", "_save": "Save"})
        self.site.refresh_from_db()
        self.assertTrue(self.site.enabled)
        self.assertEqual(self.client.post(f"/admin/auth/user/{self.admin.pk}/password/", {"password1": "changed", "password2": "changed"}).status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("test"))
