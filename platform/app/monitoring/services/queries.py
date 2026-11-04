"""Read-only projections for the dashboard and bounded binding history."""
from datetime import datetime, timedelta, timezone as dt_timezone
from math import ceil, floor

from django.utils import timezone

from monitoring.models import Binding, Device, Observation, Site

UTC = dt_timezone.utc
WORK_STATES = (
    ("radar_enabled", "待启用"),
    ("installation_confirmed", "待安装确认"),
    ("ready", "启动/模式确认中"),
    ("transport_ok", "雷达通信异常"),
)

REASON_LABELS = {
    "ok": "有效", "missing": "缺少数据", "stale": "采样已过期",
    "transport_fault": "通信异常", "installation_unconfirmed": "安装未确认",
    "invalid_value": "数值无效", "out_of_range": "超出工程门控范围",
    "occupancy_unknown": "占用未知", "not_present": "未检测到有人",
    "not_in_bed": "未检测到在床", "motion_unknown": "运动状态未知",
    "motion": "检测到运动", "conflicting_occupancy": "占用状态矛盾", "unknown": "未知",
}


def iso_time(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def metric_value(sample, name):
    low, high = (10, 25) if name == "rr" else (60, 100)
    metric = sample[name]
    if all(sample[key] for key, _ in WORK_STATES) and metric["valid"] and low <= metric["raw"] <= high:
        return metric["raw"]
    return None


def read_current(binding, now=None):
    now = now or timezone.now()
    device = binding.device
    observation = device.latest_observation
    if observation and observation.binding_id != binding.pk:
        observation = None
    received_at = device.last_fresh_received_at
    captured_at = observation.captured_at if observation else None
    if not device.enabled:
        state, label = "disabled", "已停用"
    elif not received_at:
        state, label = "waiting", "等待首包"
    elif (now - received_at).total_seconds() > 60:
        state, label = "no_report", "超过60秒无新上报"
    elif not observation or (now - received_at).total_seconds() > 30 or (now - captured_at).total_seconds() > 30:
        state, label = "expired", "观测已过期"
    else:
        state, label = "fresh", "最近有新上报"

    sample = observation.payload["sample"] if observation else None
    fault = next((label for key, label in WORK_STATES if not sample[key]), None) if sample else None
    occupancy = "未知"
    if sample and state == "fresh" and not fault:
        presence, bed = sample["presence"], sample["bed"]
        if presence["valid"] and bed["valid"]:
            if presence["raw"] == 1 and bed["raw"] == 1:
                occupancy = "最近在床"
            elif bed["raw"] == 0:
                occupancy = "最近非在床"
    return {
        "state": state, "label": label,
        "work_label": fault or ("工作条件就绪" if sample else "等待上报"),
        "needs_attention": bool(fault),
        "captured_at": captured_at, "received_at": received_at,
        "captured_ms": round(captured_at.timestamp() * 1000) if captured_at else "",
        "received_ms": round(received_at.timestamp() * 1000) if received_at else "",
        "occupancy": occupancy,
        "rr": metric_value(sample, "rr") if sample and state == "fresh" else None,
        "hr": metric_value(sample, "hr") if sample and state == "fresh" else None,
        "rr_reason": REASON_LABELS[sample["rr"]["reason"]] if sample else "尚无观测",
        "hr_reason": REASON_LABELS[sample["hr"]["reason"]] if sample else "尚无观测",
        "lamp": sample["lamp"] if sample and state == "fresh" else None,
    }


def read_overview(site_id, now=None):
    now = now or timezone.now()
    bindings = Binding.objects.filter(ended_at__isnull=True).select_related(
        "device__latest_observation", "bed__site"
    ).order_by("bed__site__name", "bed__room_label", "bed__bed_label")
    if site_id is not None:
        bindings = bindings.filter(bed__site_id=site_id)
    rows = [{"binding": binding, "snapshot": read_current(binding, now)} for binding in bindings]
    counts = {state: 0 for state in ("fresh", "expired", "no_report", "waiting", "disabled")}
    for row in rows:
        counts[row["snapshot"]["state"]] += 1
    return {
        "rows": rows, "sites": Site.objects.order_by("name"), "selected_site": site_id,
        "server_time": iso_time(now), "server_ms": round(now.timestamp() * 1000),
        "counts": {**counts, "bound": len(rows),
                   "attention": sum(row["snapshot"]["needs_attention"] for row in rows),
                   "not_fresh": len(rows) - counts["fresh"]},
    }


def history_range(binding, from_time, to_time):
    start = max(from_time, binding.started_at + timedelta(seconds=5))
    end = min(to_time, binding.ended_at or to_time)
    if start > end:
        # An empty intersection is represented by equal endpoints within the request.
        start = end = min(to_time, max(from_time, end))
    return start, end


def read_binding_history(binding, from_time, to_time, now=None):
    now = now or timezone.now()
    start, end = history_range(binding, from_time, to_time)
    first_slot = ceil(start.timestamp() / 10)
    last_slot = floor(end.timestamp() / 10)
    expected_slots = max(0, last_slot - first_slot)
    representatives = {}
    if expected_slots:
        observations = Observation.objects.filter(
            binding=binding,
            captured_at__gte=datetime.fromtimestamp(first_slot * 10, UTC),
            captured_at__lt=datetime.fromtimestamp(last_slot * 10, UTC),
        ).order_by("captured_at", "received_at", "id").values("captured_at", "payload")
        # Ordered replacement selects the last captured/received/id point in each slot.
        for observation in observations.iterator():
            representatives[floor(observation["captured_at"].timestamp() / 10)] = observation["payload"]["sample"]

    buckets = []
    rr_total = hr_total = 0
    minute = from_time
    while minute < to_time:
        first = int(minute.timestamp() // 10)
        samples = [representatives[slot] for slot in range(first, first + 6) if slot in representatives]
        rr_values = [metric_value(sample, "rr") for sample in samples]
        hr_values = [metric_value(sample, "hr") for sample in samples]
        rr_count = sum(value is not None for value in rr_values)
        hr_count = sum(value is not None for value in hr_values)
        rr_total += rr_count
        hr_total += hr_count
        buckets.append({
            "minute": iso_time(minute), "received_slots": len(samples),
            "rr_valid_slots": rr_count, "hr_valid_slots": hr_count,
            "rr_bpm": rr_values[-1] if rr_count == 6 else None,
            "hr_bpm": hr_values[-1] if hr_count == 6 else None,
        })
        minute += timedelta(minutes=1)
    received_slots = len(representatives)
    return {
        "binding_id": str(binding.pk), "server_time": iso_time(now),
        "requested_range": {"from": iso_time(from_time), "to": iso_time(to_time)},
        "effective_range": {"from": iso_time(start), "to": iso_time(end)},
        "summary": {
            "expected_slots": expected_slots, "received_slots": received_slots,
            "rr_valid_slots": rr_total, "hr_valid_slots": hr_total,
            "report_completeness": received_slots / expected_slots if expected_slots else None,
            "rr_valid_ratio": rr_total / received_slots if received_slots else None,
            "hr_valid_ratio": hr_total / received_slots if received_slots else None,
        },
        "buckets": buckets,
    }


def unbound_devices():
    return Device.objects.exclude(pk__in=Binding.objects.filter(ended_at__isnull=True).values("device_id")).order_by("display_code")
