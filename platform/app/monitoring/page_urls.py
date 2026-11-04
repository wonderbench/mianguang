from django.contrib.auth import views as auth_views
from django.urls import path

from monitoring.views import pages

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", pages.overview, name="overview"),
    path("fragments/overview/", pages.overview_fragment, name="overview_fragment"),
    path("bindings/<uuid:binding_id>/", pages.binding_detail, name="binding_detail"),
    path("api/ui/v1/bindings/<uuid:binding_id>/series", pages.binding_series, name="binding_series"),
    path("bindings/<uuid:binding_id>/export.csv", pages.binding_export, name="binding_export"),
]
