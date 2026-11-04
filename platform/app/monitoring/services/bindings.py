import hashlib
import secrets

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from monitoring.models import AuditEntry, Bed, Binding, Device, Site
from .errors import PlatformError


def require_manager(actor):
    if not actor.is_active or not actor.has_perm("monitoring.manage_platform"):
        raise PermissionDenied


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(actor, action, target, details=None):
    AuditEntry.objects.create(actor=actor, action=action, target_type=target._meta.model_name,
                              target_id=str(target.pk), details=details or {})


def issue_token(device):
    token = secrets.token_urlsafe(32)
    device.token_hash = token_digest(token)
    device.credential_changed_at = timezone.now()
    return token


def clear_latest(device):
    device.latest_observation = None
    device.last_fresh_received_at = None


@transaction.atomic
def register_device(*, actor, display_code, is_simulator=False):
    require_manager(actor)
    device = Device(display_code=display_code, is_simulator=is_simulator)
    token = issue_token(device)
    device.full_clean(exclude=["token_hash"])
    device.save()
    audit(actor, "device.register", device, {"is_simulator": is_simulator})
    return device, token


@transaction.atomic
def replace_binding(*, actor, device_id, bed_id=None, resident_alias=""):
    require_manager(actor)
    device = Device.objects.select_for_update().get(pk=device_id)
    if not device.enabled:
        raise PlatformError("device_disabled", "请先重新启用设备。")
    previous = Binding.objects.filter(device=device, ended_at__isnull=True).first()
    bed = None
    if bed_id is not None:
        # Site is locked before its Bed, matching the configuration editor.
        site_id = Bed.objects.values_list("site_id", flat=True).get(pk=bed_id)
        site = Site.objects.select_for_update().get(pk=site_id)
        bed = Bed.objects.select_for_update().get(pk=bed_id)
        if bed.site_id != site.pk:
            raise PlatformError("location_changed", "地点已变更，请刷新后重试。")
        if not bed.enabled or not site.enabled:
            raise PlatformError("location_disabled", "地点或床位已停用。")
        if Binding.objects.filter(bed=bed, ended_at__isnull=True).exclude(device=device).exists():
            raise PlatformError("bed_occupied", "床位已被分配，请先显式解绑。")
        if not resident_alias.strip() or len(resident_alias) > 64:
            raise PlatformError("invalid_alias", "住户代号需为1–64字符。", 400)
    now = timezone.now()
    if previous:
        previous.ended_at = now
        previous.save(update_fields=["ended_at"])
    binding = None
    if bed:
        binding = Binding.objects.create(device=device, bed=bed, resident_alias=resident_alias.strip(),
            location_label_snapshot=f"{site.name} / {bed.room_label} / {bed.bed_label}", started_at=now, created_by=actor)
    token = issue_token(device)
    clear_latest(device)
    device.save()
    audit(actor, "binding.replace" if binding else "binding.end", device, {
        "previous_binding_id": str(previous.pk) if previous else None,
        "binding_id": str(binding.pk) if binding else None,
    })
    return binding, token


@transaction.atomic
def disable_device(*, actor, device_id):
    require_manager(actor)
    device = Device.objects.select_for_update().get(pk=device_id)
    Binding.objects.filter(device=device, ended_at__isnull=True).update(ended_at=timezone.now())
    issue_token(device)  # Revoke the issued credential; no replacement is delivered.
    device.enabled = False
    clear_latest(device)
    device.save()
    audit(actor, "device.disable", device)


@transaction.atomic
def rotate_credential(*, actor, device_id, enable=False):
    require_manager(actor)
    device = Device.objects.select_for_update().get(pk=device_id)
    if enable:
        device.enabled = True
        clear_latest(device)
    token = issue_token(device)
    device.save()
    audit(actor, "device.enable" if enable else "credential.rotate", device)
    return token
