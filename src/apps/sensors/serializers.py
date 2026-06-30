"""
DRF serializers for the sensors app.

GeoFeatureModelSerializer (from djangorestframework-gis) emits proper
GeoJSON Feature objects for ``location`` so the dashboard's Leaflet map can
consume the API response directly without any client-side reshaping.
"""
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import SensorReading, SensorStation


class SensorReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorReading
        fields = [
            "id", "station", "water_level_cm", "rainfall_mm", "temperature_c",
            "battery_voltage", "signal_strength", "timestamp", "is_verified",
        ]
        read_only_fields = ["id", "is_verified"]


class SensorStationSerializer(GeoFeatureModelSerializer):
    """List/detail serializer — includes the latest reading inline so the
    dashboard map can render current status without a second request per
    station.
    """

    latest_reading = serializers.SerializerMethodField()

    class Meta:
        model = SensorStation
        geo_field = "location"
        fields = [
            "id", "name", "community", "status", "serial_number",
            "battery_level", "last_reading_at", "flood_zone", "latest_reading",
        ]

    def get_latest_reading(self, obj: SensorStation) -> dict | None:
        reading = obj.latest_reading()
        return SensorReadingSerializer(reading).data if reading else None


class SensorStationCreateSerializer(serializers.ModelSerializer):
    """Admin-only serializer for registering a new station -- accepts plain
    lon/lat instead of requiring callers to build GeoJSON geometry by hand.
    """

    longitude = serializers.FloatField(write_only=True)
    latitude = serializers.FloatField(write_only=True)

    class Meta:
        model = SensorStation
        fields = [
            "id", "name", "community", "serial_number", "ip_address",
            "flood_zone", "longitude", "latitude",
        ]

    def create(self, validated_data):
        from django.contrib.gis.geos import Point

        lon = validated_data.pop("longitude")
        lat = validated_data.pop("latitude")
        validated_data["location"] = Point(lon, lat, srid=4326)
        return super().create(validated_data)
