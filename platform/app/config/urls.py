from django.urls import include, path

from monitoring.admin import platform_admin
from monitoring.views.device import healthz, telemetry

urlpatterns = [
    path("admin/", platform_admin.urls),
    path("api/device/v1/telemetry", telemetry),
    path("healthz", healthz),
    path("", include("monitoring.page_urls")),
]
