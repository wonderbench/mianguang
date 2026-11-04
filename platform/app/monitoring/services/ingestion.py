import hashlib
import hmac
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from monitoring.models import Binding, Device, Observation
from .bindings import token_digest
from .errors import PlatformError

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts/telemetry.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
UTC_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")


def parse_utc(value):
    if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
        raise ValueError("UTC timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return int(number) if number.is_integer() else number


def reject_constant(value):
    raise ValueError("non-finite number")


def parse_payload(body):
    if len(body) > 4096:
        raise PlatformError("payload_too_large", "请求体最多4 KiB。", 413)
    try:
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=unique_keys,
                             parse_constant=reject_constant, parse_float=finite_number)
    except (ValueError, UnicodeError, RecursionError):
        raise PlatformError("malformed_json", "请求必须为无重复键的有效JSON。", 400) from None
    try:
        VALIDATOR.validate(payload)
        captured_at = parse_utc(payload["captured_at"])
    except (ValidationError, ValueError):
        raise PlatformError("schema_invalid", "请求不符合telemetry v1契约。", 422) from None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return payload, captured_at, hashlib.sha256(canonical.encode()).hexdigest()


def validate_quality(payload):
    sample = payload["sample"]
    for name in ("presence", "bed", "rr", "hr"):
        field = sample[name]
        if field["available"] and field["age_ms"] > payload["uptime_ms"]:
            raise PlatformError("quality_conflict", "字段年龄超过设备运行时间。", 422)
    presence, bed = sample["presence"], sample["bed"]
    if presence["valid"] and bed["valid"] and presence["raw"] == 0 and bed["raw"] == 1:
        raise PlatformError("quality_conflict", "占用观测互相冲突。", 422)


def ingest_telemetry(*, token, body):
    digest = token_digest(token)
    device_id = Device.objects.filter(token_hash=digest).values_list("pk", flat=True).first()
    if device_id is None:
        raise PlatformError("invalid_credential", "设备凭证无效。", 401)
    payload, captured_at, payload_hash = parse_payload(body)
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        if not hmac.compare_digest(device.token_hash, digest):
            raise PlatformError("invalid_credential", "设备凭证无效。", 401)
        if not device.enabled:
            raise PlatformError("device_disabled", "设备已停用。", 403)
        if UUID(payload["device_id"]) != device.pk:
            raise PlatformError("device_identity_mismatch", "凭证与设备不匹配。", 403)
        binding = Binding.objects.filter(device=device, ended_at__isnull=True).first()
        binding_id = UUID(payload["binding_id"]) if payload["binding_id"] else None
        if binding_id != (binding.pk if binding else None):
            raise PlatformError("binding_mismatch", "当前绑定与设备配置不匹配。")
        previous = Observation.objects.filter(device=device, boot_id=payload["boot_id"], seq=payload["seq"]).first()
        now = timezone.now()
        if previous:
            if previous.payload_hash != payload_hash:
                raise PlatformError("duplicate_conflict", "同一序号的内容不一致。")
            status = "duplicate"
        else:
            if not now - timedelta(seconds=20) <= captured_at <= now + timedelta(seconds=5):
                raise PlatformError("clock_out_of_window", "采集时间不在接入窗口内。", 422)
            if binding and min(now, captured_at) < binding.started_at + timedelta(seconds=5):
                raise PlatformError("binding_not_ready", "绑定尚在5秒隔离期内。")
            validate_quality(payload)
            if device.last_boot_id is not None and (
                payload["boot_id"] < device.last_boot_id
                or (payload["boot_id"] == device.last_boot_id and (
                    payload["seq"] <= device.last_seq or payload["uptime_ms"] <= device.last_uptime_ms))
                or captured_at <= device.last_captured_at
            ):
                raise PlatformError("out_of_order", "启动计数、序号或采集时间回退。")
            observation = Observation.objects.create(device=device, binding=binding,
                boot_id=payload["boot_id"], seq=payload["seq"], captured_at=captured_at, received_at=now,
                uptime_ms=payload["uptime_ms"], firmware_version=payload["firmware_version"],
                payload=payload, payload_hash=payload_hash)
            device.latest_observation = observation
            device.last_fresh_received_at = now
            device.last_boot_id = payload["boot_id"]
            device.last_seq = payload["seq"]
            device.last_uptime_ms = payload["uptime_ms"]
            device.last_captured_at = captured_at
            device.save()
            status = "accepted"
    return {"status": status, "boot_id": payload["boot_id"], "seq": payload["seq"],
            "server_time": now.isoformat().replace("+00:00", "Z")}
