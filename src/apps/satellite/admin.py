from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import FloodMap, FloodZone, SatelliteScene


@admin.register(SatelliteScene)
class SatelliteSceneAdmin(GISModelAdmin):
    list_display = ("scene_id", "source", "provider", "acquisition_date", "cloud_cover_pct", "status")
    list_filter = ("source", "provider", "status")
    search_fields = ("scene_id",)
    date_hierarchy = "acquisition_date"
    readonly_fields = ("created_at", "updated_at")
    default_lon = -0.18
    default_lat = 5.60
    default_zoom = 10


@admin.register(FloodZone)
class FloodZoneAdmin(GISModelAdmin):
    list_display = ("name", "current_risk_level", "water_level_threshold_cm",
                     "rainfall_threshold_mm", "population_estimate", "last_assessed_at")
    list_filter = ("current_risk_level",)
    search_fields = ("name",)
    default_lon = -0.18
    default_lat = 5.60
    default_zoom = 11


@admin.register(FloodMap)
class FloodMapAdmin(GISModelAdmin):
    list_display = ("flood_zone", "detection_method", "flooded_area_ha",
                     "confidence", "confirmed_by_sensors", "created_at")
    list_filter = ("detection_method", "confirmed_by_sensors", "flood_zone")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    default_lon = -0.18
    default_lat = 5.60
    default_zoom = 10
