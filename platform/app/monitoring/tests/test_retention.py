import io
from datetime import timedelta

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from monitoring.models import AuditEntry, Bed, Binding, Device, Observation, Site
from monitoring.services.bindings import register_device


class RetentionTests(TestCase):
    def test_cleanup_redacts_expired_identity_and_preserves_watermarks(self):
        now = timezone.now()
        actor = get_user_model().objects.create_superuser("admin", password="test")
        device, _ = register_device(actor=actor, display_code="A")
        site = Site.objects.create(name="A")
        bed = Bed.objects.create(site=site, room_label="1", bed_label="1")
        binding = Binding.objects.create(device=device, bed=bed, resident_alias="expired-alias", location_label_snapshot="expired-location",
            started_at=now - timedelta(days=9), ended_at=now - timedelta(days=8), created_by=actor)
        observation = Observation.objects.create(device=device, binding=binding, boot_id=4, seq=7, uptime_ms=9000,
            captured_at=now - timedelta(days=8), received_at=now - timedelta(days=8), firmware_version="synthetic", payload={}, payload_hash="fixture")
        Device.objects.filter(pk=device.pk).update(latest_observation=observation, last_fresh_received_at=observation.received_at,
            last_boot_id=4, last_seq=7, last_uptime_ms=9000, last_captured_at=observation.captured_at)
        AuditEntry.objects.create(actor=actor, action="old", target_type="device", target_id=str(device.pk), at=now - timedelta(days=91))
        LogEntry.objects.create(user=actor, content_type=ContentType.objects.get_for_model(Device), object_id=str(device.pk),
            object_repr=str(device.pk), action_flag=ADDITION, action_time=now - timedelta(days=91))
        Session.objects.create(session_key="expired", session_data="", expire_date=now - timedelta(days=1))
        call_command("purge_expired", stdout=io.StringIO())
        device.refresh_from_db()
        binding.refresh_from_db()
        self.assertFalse(Observation.objects.exists())
        self.assertIsNone(device.latest_observation_id)
        self.assertEqual((device.last_boot_id, device.last_seq, device.last_uptime_ms), (4, 7, 9000))
        self.assertEqual(device.last_fresh_received_at, observation.received_at)
        self.assertEqual((binding.resident_alias, binding.location_label_snapshot), ("", ""))
        self.assertFalse(AuditEntry.objects.filter(action="old").exists())
        self.assertFalse(LogEntry.objects.exists())
        self.assertFalse(Session.objects.exists())
