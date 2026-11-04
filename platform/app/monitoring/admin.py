from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import AuditEntry, Bed, Binding, Device, Site
from .services.bindings import audit, disable_device, register_device, replace_binding, rotate_credential
from .services.errors import PlatformError


class ManagerLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.has_perm("monitoring.manage_platform"):
            raise forms.ValidationError("此账号没有平台管理权限。")


class PlatformAdminSite(admin.AdminSite):
    site_header = "眠光 · 平台管理"
    site_title = "眠光管理"
    login_form = ManagerLoginForm

    def has_permission(self, request):
        return request.user.is_active and request.user.has_perm("monitoring.manage_platform")

    def admin_view(self, view, cacheable=False):
        wrapped = super().admin_view(view, cacheable)

        def guarded(request, *args, **kwargs):
            if request.user.is_authenticated and not self.has_permission(request):
                return HttpResponseForbidden("仅管理员可访问。")
            return wrapped(request, *args, **kwargs)

        return guarded

    def login(self, request, extra_context=None):
        if request.user.is_authenticated and not self.has_permission(request):
            return HttpResponseForbidden("仅管理员可访问。")
        return super().login(request, extra_context)


platform_admin = PlatformAdminSite(name="admin")


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


class LocationAdmin(NoDeleteAdmin):
    def changeform_view(self, request, *args, **kwargs):
        try:
            return super().changeform_view(request, *args, **kwargs)
        except PlatformError as exc:
            self.message_user(request, exc.message, messages.ERROR)
            return redirect(request.path)

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if isinstance(obj, Site):
            if change:
                Site.objects.select_for_update().get(pk=obj.pk)
            occupied = Binding.objects.filter(bed__site=obj, ended_at__isnull=True).exists() if change else False
        else:
            Site.objects.select_for_update().get(pk=obj.site_id)
            if change:
                Bed.objects.select_for_update().get(pk=obj.pk)
            occupied = Binding.objects.filter(bed=obj, ended_at__isnull=True).exists() if change else False
        if not obj.enabled and occupied:
            raise PlatformError("location_in_use", "请先结束该地点/床位的活动绑定，再停用。")
        obj.save()
        audit(request.user, "location.update" if change else "location.create", obj, {"fields": form.changed_data})


@admin.register(Site, site=platform_admin)
class SiteAdmin(LocationAdmin):
    list_display = ("name", "enabled")


@admin.register(Bed, site=platform_admin)
class BedAdmin(LocationAdmin):
    list_display = ("site", "room_label", "bed_label", "enabled")
    list_filter = ("site", "enabled")
    list_select_related = ("site",)

    def get_readonly_fields(self, request, obj=None):
        return ("site",) if obj else ()


class DeviceActionForm(forms.Form):
    operation = forms.ChoiceField(label="操作", choices=[("bind", "绑定 / 换人 / 换床"), ("end", "解绑并发放无绑定诊断配置"),
        ("rotate", "轮换凭证"), ("disable", "停用并撤销凭证"), ("enable", "重新启用并发放诊断配置")])
    bed = forms.ModelChoiceField(label="目标床位", queryset=Bed.objects.filter(enabled=True, site__enabled=True).select_related("site"), required=False)
    resident_alias = forms.CharField(label="住户代号", max_length=64, required=False)

    def clean(self):
        data = super().clean()
        if data.get("operation") == "bind" and (not data.get("bed") or not data.get("resident_alias")):
            raise forms.ValidationError("绑定需要床位和内部住户代号。")
        return data


@admin.register(Device, site=platform_admin)
class DeviceAdmin(NoDeleteAdmin):
    list_display = ("display_code", "is_simulator", "enabled", "last_fresh_received_at", "operations")
    list_filter = ("enabled", "is_simulator")
    search_fields = ("display_code",)
    fields = ("id", "display_code", "is_simulator", "enabled", "credential_changed_at", "last_fresh_received_at", "diagnostics", "operations")

    def get_readonly_fields(self, request, obj=None):
        fields = ("id", "enabled", "credential_changed_at", "last_fresh_received_at", "diagnostics", "operations")
        return fields + (("is_simulator",) if obj else ())

    @admin.display(description="安装与凭证")
    def operations(self, obj):
        if not obj.pk or not obj.token_hash:
            return "登记后可配置"
        return format_html('<a href="{}">绑定 / 解绑 / 轮换 / 停用</a>', reverse("admin:monitoring_device_configure", args=[obj.pk]))

    @admin.display(description="最近工程诊断（原始快照；是否过期以采集/接收时间为准）")
    def diagnostics(self, obj):
        if not obj.latest_observation_id:
            return "待首次上报"
        observation = obj.latest_observation
        return {"captured_at": observation.captured_at, "received_at": observation.received_at, "sample": observation.payload["sample"]}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("latest_observation")

    def get_urls(self):
        return [path("<uuid:device_id>/configure/", self.admin_site.admin_view(self.configure), name="monitoring_device_configure")] + super().get_urls()

    def save_model(self, request, obj, form, change):
        if change:
            with transaction.atomic():
                Device.objects.select_for_update().get(pk=obj.pk)
                obj.save(update_fields=["display_code"])
                audit(request.user, "device.update", obj, {"fields": ["display_code"]})
        else:
            device, request.issued_token = register_device(actor=request.user, display_code=obj.display_code, is_simulator=obj.is_simulator)
            obj.__dict__.update(device.__dict__)

    def token_response(self, request, device, token):
        binding = Binding.objects.filter(device=device, ended_at__isnull=True).first()
        response = render(request, "admin/monitoring/credential.html", {**self.admin_site.each_context(request),
            "device": device, "token": token, "binding_id": str(binding.pk) if binding else "null"})
        response["Cache-Control"] = "no-store"
        return response

    def response_add(self, request, obj, post_url_continue=None):
        return self.token_response(request, obj, request.issued_token)

    def configure(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id)
        form = DeviceActionForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                if data["operation"] == "disable":
                    disable_device(actor=request.user, device_id=device.pk)
                    self.message_user(request, "设备已停用，原配置凭证已撤销。")
                    return redirect("admin:monitoring_device_changelist")
                if data["operation"] in ("bind", "end"):
                    _, token = replace_binding(actor=request.user, device_id=device.pk,
                        bed_id=data["bed"].pk if data["operation"] == "bind" else None, resident_alias=data["resident_alias"])
                else:
                    token = rotate_credential(actor=request.user, device_id=device.pk, enable=data["operation"] == "enable")
                device.refresh_from_db()
                return self.token_response(request, device, token)
            except PlatformError as exc:
                form.add_error(None, exc.message)
        return render(request, "admin/monitoring/configure.html", {**self.admin_site.each_context(request), "device": device, "form": form})


class ReadOnlyAdmin(NoDeleteAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Binding, site=platform_admin)
class BindingAdmin(ReadOnlyAdmin):
    list_display = ("id", "device", "location_label_snapshot", "resident_alias", "started_at", "ended_at", "history")
    list_select_related = ("device",)

    @admin.display(description="观测")
    def history(self, obj):
        return format_html('<a href="/bindings/{}/">绑定历史</a>', obj.pk)


@admin.register(AuditEntry, site=platform_admin)
class AuditAdmin(ReadOnlyAdmin):
    list_display = ("at", "actor", "action", "target_type", "target_id")
    list_filter = ("action",)


@admin.register(get_user_model(), site=platform_admin)
class PlatformUserAdmin(UserAdmin):
    def has_change_permission(self, request, obj=None):
        if obj and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        return () if request.user.is_superuser else ("is_superuser", "user_permissions")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = get_user_model().objects.get(pk=form.instance.pk)
        user.is_staff = user.has_perm("monitoring.manage_platform")
        user.save(update_fields=["is_staff"])
        audit(request.user, "account.update" if change else "account.create", user, {"fields": form.changed_data})
