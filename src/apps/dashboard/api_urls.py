"""URL routing for the dashboard stats API (separate from the page-rendering
urls.py, which is included under /dashboard/ -- these are included under
/api/dashboard/ alongside the other apps' REST APIs).
"""
from django.urls import path

from . import api_views

urlpatterns = [
    path("dashboard/stats/overview/", api_views.overview_stats, name="dashboard-stats-overview"),
    path("dashboard/stats/water-level-trend/", api_views.water_level_trend, name="dashboard-stats-water-level"),
    path("dashboard/stats/alerts-trend/", api_views.alerts_trend, name="dashboard-stats-alerts-trend"),
    path("dashboard/stats/rainfall-trend/", api_views.rainfall_trend, name="dashboard-stats-rainfall-trend"),
    path("dashboard/stats/flood-events-by-zone/", api_views.flood_events_by_zone, name="dashboard-stats-events-by-zone"),
    path("dashboard/stats/station-battery/", api_views.station_battery_levels, name="dashboard-stats-battery"),
    path("dashboard/stats/map-heatmap/", api_views.map_heatmap_points, name="dashboard-stats-heatmap"),
    path("dashboard/stats/station/<int:station_id>/detail/", api_views.station_detail_stats, name="dashboard-stats-station-detail"),
    path("dashboard/stats/zone-risk-scores/", api_views.zone_risk_scores, name="dashboard-stats-zone-risk-scores"),
]
