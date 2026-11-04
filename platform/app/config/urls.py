from django.contrib import admin
from django.urls import path

from monitoring.views.device import healthz, telemetry

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/device/v1/telemetry", telemetry),
    path("healthz", healthz),
]
