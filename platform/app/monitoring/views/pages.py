import csv
from datetime import datetime, timedelta, timezone as dt_timezone
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from monitoring.models import Binding, Observation
from monitoring.services.bindings import audit
from monitoring.services.queries import (
    history_range, iso_time, read_binding_history, read_current, read_overview, unbound_devices,
)


def permitted(user, permission):
    return user.is_superuser or user.has_perm(f"monitoring.{permission}")


def dashboard_required(view=None, *, json_response=False):
    def decorate(func):
        @wraps(func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if json_response:
                    return JsonResponse({"error": "authentication_required"}, status=401)
                return redirect_to_login(request.get_full_path())
            if not permitted(request.user, "view_dashboard"):
                return JsonResponse({"error": "permission_denied"}, status=403) if json_response else HttpResponse("无权访问。", status=403)
            return func(request, *args, **kwargs)
        return wrapped
    return decorate(view) if view else decorate


def page_context(request):
    return {
        "can_manage": permitted(request.user, "manage_platform"),
        "can_export": permitted(request.user, "manage_platform") and permitted(request.user, "export_observation"),
        "demo_mode": settings.DEMO_MODE,
    }


def overview_context(request):
    site = request.GET.get("site")
    if site and (not site.isascii() or not site.isdecimal()):
        raise ValueError("invalid_site")
    context = read_overview(int(site) if site else None)
    context.update(page_context(request))
    if context["can_manage"]:
        context["unbound_devices"] = unbound_devices()
    return context


@never_cache
@require_GET
@dashboard_required
def overview(request):
    try:
        context = overview_context(request)
    except ValueError:
        return HttpResponse("地点参数无效。", status=400)
    return render(request, "monitoring/overview.html", context)


@never_cache
@require_GET
@dashboard_required
def overview_fragment(request):
    try:
        context = overview_context(request)
    except ValueError:
        return HttpResponse("地点参数无效。", status=400)
    return render(request, "monitoring/_overview.html", context)


def get_binding(binding_id):
    return get_object_or_404(Binding.objects.select_related("device__latest_observation", "bed__site"), pk=binding_id)


@never_cache
@require_GET
@dashboard_required
def binding_detail(request, binding_id):
    binding = get_binding(binding_id)
    now = timezone.now()
    to_time = now.replace(second=0, microsecond=0)
    context = {
        **page_context(request), "binding": binding,
        "server_ms": round(now.timestamp() * 1000),
        "server_time": iso_time(now),
        "initial_from": iso_time(to_time - timedelta(hours=8)), "initial_to": iso_time(to_time),
    }
    if binding.ended_at is None:
        context["snapshot"] = read_current(binding, now)
    return render(request, "monitoring/binding.html", context)


def parse_range(request, now):
    values = []
    for key in ("from", "to"):
        raw = request.GET.get(key, "")
        # Require an explicit ISO timestamp in UTC, not a local or date-only value.
        if "T" not in raw:
            raise ValueError("invalid_range")
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() != timedelta(0) or value.second or value.microsecond:
            raise ValueError("invalid_range")
        values.append(value.astimezone(dt_timezone.utc))
    start, end = values
    current_minute = now.replace(second=0, microsecond=0)
    if not (current_minute - timedelta(days=7) <= start < end <= current_minute and end - start <= timedelta(hours=24)):
        raise ValueError("invalid_range")
    return start, end


@never_cache
@require_GET
@dashboard_required(json_response=True)
def binding_series(request, binding_id):
    binding = get_binding(binding_id)
    now = timezone.now()
    try:
        start, end = parse_range(request, now)
    except ValueError:
        return JsonResponse({"error": "invalid_range"}, status=400)
    return JsonResponse(read_binding_history(binding, start, end, now))


def csv_text(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


@never_cache
@require_GET
@dashboard_required
def binding_export(request, binding_id):
    if not permitted(request.user, "manage_platform") or not permitted(request.user, "export_observation"):
        return HttpResponse("无权导出。", status=403)
    binding = get_binding(binding_id)
    try:
        start, end = parse_range(request, timezone.now())
    except ValueError:
        return JsonResponse({"error": "invalid_range"}, status=400)
    effective_start, effective_end = history_range(binding, start, end)
    observations = Observation.objects.filter(
        binding=binding, captured_at__gte=effective_start, captured_at__lt=effective_end,
    ).order_by("captured_at", "received_at", "id")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="binding-{binding.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    fields = ("presence", "bed", "rr", "hr")
    writer.writerow([
        "binding_id", "location_label_snapshot", "resident_alias", "device_id", "is_simulator",
        "boot_id", "seq", "captured_at", "received_at", "firmware_version",
        *[f"{name}_{field}" for name in fields for field in ("raw", "available", "valid", "reason", "age_ms")],
        "radar_enabled", "installation_confirmed", "ready", "transport_ok", "lamp_mode", "lamp_pwm", "lamp_target",
    ])
    count = 0
    for observation in observations.iterator():
        sample = observation.payload["sample"]
        row = [
            str(binding.pk), binding.location_label_snapshot, binding.resident_alias, str(binding.device_id),
            binding.device.is_simulator, observation.boot_id, observation.seq,
            iso_time(observation.captured_at), iso_time(observation.received_at), observation.firmware_version,
            *[sample[name][field] for name in fields for field in ("raw", "available", "valid", "reason", "age_ms")],
            *[sample[key] for key in ("radar_enabled", "installation_confirmed", "ready", "transport_ok")],
            sample["lamp"]["mode"], sample["lamp"]["pwm"], sample["lamp"]["target"],
        ]
        writer.writerow([csv_text(value) for value in row])
        count += 1
    audit(request.user, "export.observations", binding, {
        "from": iso_time(start), "to": iso_time(end), "row_count": count,
    })
    return response
