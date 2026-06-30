"""DRF serializers for the satellite app."""
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import FloodMap, FloodZone, SatelliteScene


class FloodZoneSerializer(GeoFeatureModelSerializer):
    """List/detail serializer for flood risk zones, GeoJSON-shaped so the
    dashboard map can render zone polygons directly.
    """

    station_count = serializers.SerializerMethodField()

    class Meta:
        model = FloodZone
        geo_field = "geometry"
        fields = [
            "id", "name", "description", "current_risk_level",
            "water_level_threshold_cm", "rainfall_threshold_mm",
            "population_estimate", "last_assessed_at", "station_count",
        ]

    def get_station_count(self, obj: FloodZone) -> int:
        return obj.stations.count()


class FloodZoneRiskSerializer(serializers.ModelSerializer):
    """Lightweight serializer for GET /api/flood-zones/{id}/risk -- just
    the current risk assessment, not the full geometry/station payload.
    """

    active_event_severity = serializers.SerializerMethodField()

    class Meta:
        model = FloodZone
        fields = ["id", "name", "current_risk_level", "last_assessed_at", "active_event_severity"]

    def get_active_event_severity(self, obj: FloodZone) -> str | None:
        event = obj.flood_events.filter(ended_at__isnull=True).first()
        return event.severity if event else None


class SatelliteSceneSerializer(serializers.ModelSerializer):
    class Meta:
        model = SatelliteScene
        fields = [
            "id", "scene_id", "source", "provider", "acquisition_date",
            "cloud_cover_pct", "status", "created_at",
        ]


class FloodMapSerializer(GeoFeatureModelSerializer):
    flood_zone_name = serializers.CharField(source="flood_zone.name", read_only=True, default=None)
    source_scene_id = serializers.CharField(source="source_scene.scene_id", read_only=True, default=None)

    class Meta:
        model = FloodMap
        geo_field = "extent_geometry"
        fields = [
            "id", "flood_zone", "flood_zone_name", "source_scene_id",
            "flooded_area_ha", "confidence", "confirmed_by_sensors",
            "detection_method", "statistics", "created_at",
        ]
