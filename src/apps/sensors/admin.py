from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import SensorReading, SensorStation


class SensorReadingInline(admin.TabularInline):
    model = SensorReading
    extra = 0
    readonly_fields = ("water_level_cm", "rainfall_mm", "temperature_c", "timestamp", "is_verified")
    ordering = ("-timestamp",)
    max_num = 10
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Readings come from the ingestion pipeline, not manual entry.
        return False


@admin.register(SensorStation)
class SensorStationAdmin(GISModelAdmin):
    list_display = ("name", "serial_number", "community", "status", "battery_level", "last_reading_at")
    list_filter = ("status", "community", "flood_zone")
    search_fields = ("name", "serial_number", "community")
    readonly_fields = ("installed_date", "last_reading_at")
    inlines = [SensorReadingInline]
    default_lon = -0.18
    default_lat = 5.60
    default_zoom = 11


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ("station", "water_level_cm", "rainfall_mm", "timestamp", "is_verified")
    list_filter = ("is_verified", "station")
    search_fields = ("station__name", "station__serial_number")
    date_hierarchy = "timestamp"
    readonly_fields = ("created_at", "updated_at")
