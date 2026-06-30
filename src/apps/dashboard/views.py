"""
Dashboard views: server-rendered pages that wrap the JSON API in a human
interface (Leaflet map, Chart.js sensor charts, alert feed, report
submission form).

Every page here is intentionally thin -- it renders a template shell with
just enough server-side context to draw the initial state, then JavaScript
(``static/js/floodwatch-realtime.js`` + per-page scripts) calls the same
DRF API endpoints built in apps.sensors/satellite/alerts to populate and
live-update the page. This avoids maintaining two parallel data-access
paths (one for templates, one for the API) for the same underlying models.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views import View


class DashboardIndexView(View):
    """GET /dashboard/ — overview: status banner, map preview, recent alerts."""

    def get(self, request):
        from apps.alerts.models import Alert, CommunityReport, FloodEvent
        from apps.satellite.models import FloodZone
        from apps.sensors.models import SensorStation, StationStatus

        context = {
            "active_nav": "dashboard",
            "zones": FloodZone.objects.all(),
            "recent_alerts": Alert.objects.select_related("recipient", "flood_event")[:10],
            "active_events": FloodEvent.objects.filter(ended_at__isnull=True).select_related("flood_zone"),
            "station_summary": {
                "total": SensorStation.objects.count(),
                "online": SensorStation.objects.filter(status=StationStatus.ONLINE).count(),
            },
            "unverified_report_count": CommunityReport.objects.filter(is_verified=False).count(),
            "accra_center": {"lat": 5.60, "lon": -0.20},  # map default view
        }
        return render(request, "dashboard/index.html", context)


class MapView(View):
    """GET /dashboard/map/ — full-page interactive Leaflet map: sensor
    stations, flood zones, and the latest satellite flood extent, all on
    one canvas. Data is loaded client-side from the JSON API (this view
    only needs to render the page shell + initial centre point).
    """

    def get(self, request):
        context = {"active_nav": "map", "accra_center": {"lat": 5.60, "lon": -0.20}}
        return render(request, "dashboard/map.html", context)


class SensorsView(View):
    """GET /dashboard/sensors/ — sensor station list + per-station chart."""

    def get(self, request):
        from apps.sensors.models import SensorStation

        context = {
            "active_nav": "sensors",
            "stations": SensorStation.objects.select_related("flood_zone").order_by("name"),
        }
        return render(request, "dashboard/sensors.html", context)


class AlertsView(View):
    """GET /dashboard/alerts/ — alert history with severity filters."""

    def get(self, request):
        from apps.alerts.models import Alert, FloodEvent

        context = {
            "active_nav": "alerts",
            "events": FloodEvent.objects.select_related("flood_zone").order_by("-started_at")[:50],
            "recent_alerts": Alert.objects.select_related("recipient", "flood_event").order_by("-created_at")[:100],
        }
        return render(request, "dashboard/alerts.html", context)


class ReportsView(View):
    """GET /dashboard/reports/ — community report feed + submission form."""

    def get(self, request):
        from apps.alerts.models import CommunityReport
        from apps.satellite.models import FloodZone

        all_reports = CommunityReport.objects.select_related("flood_zone")
        context = {
            "active_nav": "reports",
            "reports": all_reports.order_by("-created_at")[:50],
            "zones": FloodZone.objects.all(),
            "verified_count": all_reports.filter(is_verified=True).count(),
            "unverified_count": all_reports.filter(is_verified=False).count(),
        }
        return render(request, "dashboard/reports.html", context)


class WeatherView(View):
    """GET /dashboard/weather/ — live weather + rainfall-forecast page.

    Rainfall is the leading indicator of flash flooding in Accra, so this
    page is the system's *forward-looking* counterpart to the satellite
    flood maps (which show standing water now). The page shell renders
    server-side; all live data is loaded client-side from the weather API
    so it can auto-refresh on an interval without a full page reload.
    """

    def get(self, request):
        context = {
            "active_nav": "weather",
            "accra_center": {"lat": 5.60, "lon": -0.20},
        }
        return render(request, "dashboard/weather.html", context)


@login_required
def settings_view(request):
    """GET /dashboard/settings/ — threshold + system configuration
    (staff only; non-staff users are redirected by the ``user_passes_test``
    check below rather than just hiding the nav link, since a hidden link
    is not access control).
    """
    if not request.user.is_staff:
        from django.contrib import messages
        from django.shortcuts import redirect

        messages.error(request, "You do not have permission to view system settings.")
        return redirect("dashboard:index")

    from apps.satellite.models import FloodZone

    context = {"active_nav": "settings", "zones": FloodZone.objects.all()}
    return render(request, "dashboard/settings.html", context)


class FloodMapsView(View):
    """GET /dashboard/flood-maps/ — satellite-derived flood map gallery."""

    def get(self, request):
        from apps.satellite.models import FloodMap

        context = {
            "active_nav": "flood_maps",
            "flood_maps": FloodMap.objects.select_related("flood_zone", "source_scene").order_by("-created_at")[:30],
        }
        return render(request, "satellite/flood_maps.html", context)


class TimeseriesView(View):
    """GET /dashboard/flood-maps/timeseries/ — historical flood trend
    analysis (NDVI/MNDWI-style spectral trend charts + historical flood
    record overlay).
    """

    def get(self, request):
        from apps.alerts.models import HistoricalFloodRecord

        context = {
            "active_nav": "flood_maps",
            "historical_records": HistoricalFloodRecord.objects.select_related("flood_zone").order_by("-event_date")[:50],
        }
        return render(request, "satellite/timeseries.html", context)
