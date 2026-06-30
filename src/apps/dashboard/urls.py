"""URL routing for the dashboard app (server-rendered pages)."""
from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardIndexView.as_view(), name="index"),
    path("map/", views.MapView.as_view(), name="map"),
    path("sensors/", views.SensorsView.as_view(), name="sensors"),
    path("alerts/", views.AlertsView.as_view(), name="alerts"),
    path("reports/", views.ReportsView.as_view(), name="reports"),
    path("flood-maps/", views.FloodMapsView.as_view(), name="flood_maps"),
    path("flood-maps/timeseries/", views.TimeseriesView.as_view(), name="timeseries"),
    path("settings/", views.settings_view, name="settings"),
]
