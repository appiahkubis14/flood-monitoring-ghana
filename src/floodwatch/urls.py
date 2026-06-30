"""
Root URL configuration for FloodWatch Ghana.

Routes:
  /admin/             Django admin
  /api/...            DRF API (per-app routers, see apps/*/urls.py)
  /api/schema/        OpenAPI schema (drf-spectacular)
  /api/docs/          Swagger UI
  /accounts/          Auth (login/logout/registration)
  /dashboard/         Community + admin dashboard
  /                   Redirects to /dashboard/
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
    path("api/", include("apps.sensors.urls")),
    path("api/", include("apps.satellite.urls")),
    path("api/", include("apps.alerts.urls")),
    path("api/", include("apps.dashboard.api_urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="account/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
