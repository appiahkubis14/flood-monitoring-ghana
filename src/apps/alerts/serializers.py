"""DRF serializers for the alerts app."""
from __future__ import annotations

from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import Alert, AlertRecipient, CommunityReport, FloodEvent


class FloodEventSerializer(serializers.ModelSerializer):
    flood_zone_name = serializers.CharField(source="flood_zone.name", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = FloodEvent
        fields = [
            "id", "flood_zone", "flood_zone_name", "severity", "triggered_by",
            "started_at", "ended_at", "is_active", "affected_area_ha",
            "peak_water_level_cm", "description",
        ]


class AlertSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source="recipient.full_name", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "uuid", "flood_event", "recipient", "recipient_name", "severity",
            "channel", "message", "delivery_status", "sent_at", "delivered_at", "created_at",
        ]
        read_only_fields = fields


class AlertRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRecipient
        fields = [
            "id", "full_name", "phone_number", "preferred_channel",
            "flood_zones", "min_severity", "is_active",
        ]


class AlertRecipientSubscribeSerializer(serializers.Serializer):
    """Public self-service subscription endpoint payload -- deliberately
    not a ModelSerializer so anonymous callers can subscribe with just a
    phone number, without exposing the full AlertRecipient field set
    (e.g. ``is_active``, which should not be directly settable by the
    public).
    """

    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20)
    preferred_channel = serializers.ChoiceField(
        choices=["whatsapp", "sms", "email", "dashboard"], default="whatsapp"
    )
    flood_zone_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    min_severity = serializers.ChoiceField(choices=["green", "yellow", "orange", "red"], default="orange")

    def create(self, validated_data):
        zone_ids = validated_data.pop("flood_zone_ids", [])
        recipient, _ = AlertRecipient.objects.update_or_create(
            phone_number=validated_data["phone_number"],
            defaults={
                "full_name": validated_data.get("full_name", ""),
                "preferred_channel": validated_data.get("preferred_channel", "whatsapp"),
                "min_severity": validated_data.get("min_severity", "orange"),
                "is_active": True,
            },
        )
        if zone_ids:
            recipient.flood_zones.set(zone_ids)
        return recipient


class CommunityReportSerializer(GeoFeatureModelSerializer):
    reporter_username = serializers.CharField(source="reporter.username", read_only=True, default=None)

    class Meta:
        model = CommunityReport
        geo_field = "location"
        fields = [
            "uuid", "reporter_username", "reporter_phone", "flood_zone",
            "severity", "description", "photo", "is_verified", "created_at",
        ]
        read_only_fields = ["uuid", "is_verified", "created_at", "reporter_username"]


class CommunityReportCreateSerializer(serializers.ModelSerializer):
    """Write serializer for public report submission -- accepts plain
    lon/lat (matching the pattern used in
    ``apps.sensors.serializers.SensorStationCreateSerializer``) rather
    than requiring GeoJSON geometry input from a mobile/web client.
    """

    longitude = serializers.FloatField(write_only=True)
    latitude = serializers.FloatField(write_only=True)

    class Meta:
        model = CommunityReport
        fields = [
            "reporter_phone", "flood_zone", "severity", "description",
            "photo", "longitude", "latitude",
        ]

    def create(self, validated_data):
        from django.contrib.gis.geos import Point

        lon = validated_data.pop("longitude")
        lat = validated_data.pop("latitude")
        validated_data["location"] = Point(lon, lat, srid=4326)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["reporter"] = request.user
        return super().create(validated_data)
