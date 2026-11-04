import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Site(models.Model):
    name = models.CharField("地点", max_length=64, unique=True)
    enabled = models.BooleanField("启用", default=True)

    def __str__(self):
        return self.name


class Bed(models.Model):
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="beds")
    room_label = models.CharField("房间", max_length=40)
    bed_label = models.CharField("床位", max_length=40)
    enabled = models.BooleanField("启用", default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "room_label", "bed_label"], name="unique_bed_location")]

    def __str__(self):
        return f"{self.site} / {self.room_label} / {self.bed_label}"


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_code = models.CharField("设备编号", max_length=64, unique=True)
    enabled = models.BooleanField("启用", default=True)
    is_simulator = models.BooleanField("模拟设备", default=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    credential_changed_at = models.DateTimeField(default=timezone.now, editable=False)
    latest_observation = models.ForeignKey("Observation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_fresh_received_at = models.DateTimeField(null=True, blank=True)
    last_boot_id = models.PositiveBigIntegerField(null=True, blank=True)
    last_seq = models.PositiveBigIntegerField(null=True, blank=True)
    last_uptime_ms = models.PositiveBigIntegerField(null=True, blank=True)
    last_captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("view_dashboard", "查看总览和绑定趋势"),
            ("manage_platform", "管理平台账号、设备和绑定"),
            ("export_observation", "导出绑定原始观测"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(last_boot_id__isnull=True) | Q(last_boot_id__range=(1, 4294967295)), name="device_boot_range"),
            models.CheckConstraint(condition=Q(last_seq__isnull=True) | Q(last_seq__lte=4294967295), name="device_seq_range"),
            models.CheckConstraint(condition=Q(last_uptime_ms__isnull=True) | Q(last_uptime_ms__lte=9007199254740991), name="device_uptime_range"),
        ]

    def __str__(self):
        return str(self.id)


class Binding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="bindings")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="bindings")
    resident_alias = models.CharField("住户代号", max_length=64)
    location_label_snapshot = models.CharField(max_length=160)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device"], condition=Q(ended_at__isnull=True), name="one_active_binding_per_device"),
            models.UniqueConstraint(fields=["bed"], condition=Q(ended_at__isnull=True), name="one_active_binding_per_bed"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("started_at")), name="binding_time_order"),
        ]

    def __str__(self):
        return str(self.id)


class Observation(models.Model):
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="observations")
    binding = models.ForeignKey(Binding, null=True, blank=True, on_delete=models.PROTECT, related_name="observations")
    boot_id = models.PositiveBigIntegerField()
    seq = models.PositiveBigIntegerField()
    captured_at = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now)
    uptime_ms = models.PositiveBigIntegerField()
    firmware_version = models.CharField(max_length=64)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "boot_id", "seq"], name="unique_device_packet"),
            models.CheckConstraint(condition=Q(boot_id__range=(1, 4294967295)), name="observation_boot_range"),
            models.CheckConstraint(condition=Q(seq__lte=4294967295), name="observation_seq_range"),
            models.CheckConstraint(condition=Q(uptime_ms__lte=9007199254740991), name="observation_uptime_range"),
        ]
        indexes = [
            models.Index(fields=["binding", "captured_at", "id"], name="observation_binding_time"),
            models.Index(fields=["device", "captured_at", "id"], name="observation_device_time"),
            models.Index(fields=["received_at"], name="observation_received"),
        ]


class AuditEntry(models.Model):
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=32)
    target_id = models.CharField(max_length=64)
    details = models.JSONField(default=dict)
