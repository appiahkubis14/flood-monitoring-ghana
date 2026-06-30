"""
API views for the sensors app.

Public endpoints (station list, readings) are read-only for anonymous
users per the project's DEFAULT_PERMISSION_CLASSES
(IsAuthenticatedOrReadOnly); registering/updating a station requires admin
authentication, enforced per-view below rather than relying solely on the
global default.
"""
from __future__ import annotations

from django_filters import rest_framework as df_filters
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SensorReading, SensorStation
from .serializers import (
    SensorReadingSerializer,
    SensorStationCreateSerializer,
    SensorStationSerializer,
)


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allows safe (GET/HEAD/OPTIONS) methods to anyone, write methods only
    to staff/admin users -- used for station registration and threshold
    updates, which must not be exposed to anonymous API callers.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class SensorStationFilter(df_filters.FilterSet):
    class Meta:
        model = SensorStation
        fields = ["status", "community", "flood_zone"]


class SensorStationViewSet(viewsets.ModelViewSet):
    """
    list:        GET  /api/sensors/                 All sensor stations (GeoJSON FeatureCollection)
    retrieve:    GET  /api/sensors/{id}/             Single station detail
    readings:    GET  /api/sensors/{id}/readings/    Time-series readings for one station
    create:      POST /api/sensors/                 Register a new station (admin only)
    """

    queryset = SensorStation.objects.select_related("flood_zone").all()
    permission_classes = [IsAdminOrReadOnly]
    filterset_class = SensorStationFilter
    search_fields = ["name", "serial_number", "community"]
    ordering_fields = ["name", "last_reading_at", "battery_level"]

    def get_serializer_class(self):
        if self.action == "create":
            return SensorStationCreateSerializer
        return SensorStationSerializer

    @action(detail=True, methods=["get"])
    def readings(self, request, pk=None):
        """GET /api/sensors/{id}/readings/?hours=24 — time-series for one station."""
        station = self.get_object()
        hours = int(request.query_params.get("hours", 24))
        from django.utils import timezone
        from datetime import timedelta

        since = timezone.now() - timedelta(hours=hours)
        qs = station.readings.filter(timestamp__gte=since).order_by("timestamp")
        page = self.paginate_queryset(qs)
        serializer = SensorReadingSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class SensorReadingViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/sensor-readings/   All readings (heavily paginated; prefer the
                                           per-station /readings/ endpoint above for normal use)
    retrieve: GET /api/sensor-readings/{id}/
    """

    queryset = SensorReading.objects.select_related("station").all()
    serializer_class = SensorReadingSerializer
    filterset_fields = ["station", "is_verified"]
    ordering_fields = ["timestamp"]
