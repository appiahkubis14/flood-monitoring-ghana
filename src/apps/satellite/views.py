"""
API views for the satellite app.

Implements, from the project brief:
  GET  /api/flood-maps/latest      Latest flood extent map
  GET  /api/flood-zones/           Flood risk zones list
  GET  /api/flood-zones/{id}/risk  Current risk level for one zone
  POST /api/admin/satellite/run    Trigger satellite monitoring (admin only)
"""
from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.sensors.views import IsAdminOrReadOnly

from .models import FloodMap, FloodZone, SatelliteScene
from .serializers import (
    FloodMapSerializer,
    FloodZoneRiskSerializer,
    FloodZoneSerializer,
    SatelliteSceneSerializer,
)


class FloodZoneViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/flood-zones/             All flood risk zones (GeoJSON)
    retrieve: GET /api/flood-zones/{id}/         Single zone detail
    risk:     GET /api/flood-zones/{id}/risk/    Current risk level only
    """

    queryset = FloodZone.objects.all()
    serializer_class = FloodZoneSerializer

    def get_serializer_class(self):
        if self.action == "risk":
            return FloodZoneRiskSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["get"])
    def risk(self, request, pk=None):
        zone = self.get_object()
        return Response(FloodZoneRiskSerializer(zone).data)


class FloodMapViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/flood-maps/           All flood maps, most recent first
    retrieve: GET /api/flood-maps/{id}/      Single flood map detail
    latest:   GET /api/flood-maps/latest/    Most recent flood map (optionally ?zone=<id>)
    """

    queryset = FloodMap.objects.select_related("flood_zone", "source_scene").order_by("-created_at")
    serializer_class = FloodMapSerializer
    filterset_fields = ["flood_zone", "confirmed_by_sensors", "detection_method"]

    @action(detail=False, methods=["get"])
    def latest(self, request):
        qs = self.get_queryset()
        zone_id = request.query_params.get("zone")
        if zone_id:
            qs = qs.filter(flood_zone_id=zone_id)
        instance = qs.first()
        if instance is None:
            return Response({"detail": "No flood maps available."}, status=404)
        return Response(self.get_serializer(instance).data)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def trigger_satellite_run(request):
    """POST /api/admin/satellite/run -- manually trigger a satellite
    monitoring cycle (admin only). Returns immediately with the Celery
    task id; the cycle itself runs asynchronously since it can take
    several minutes (download + preprocess for multiple scenes).
    """
    from apps.satellite.tasks import process_satellite_data

    task = process_satellite_data.delay()
    return Response({"task_id": task.id, "status": "queued"}, status=202)


class SatelliteSceneViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/satellite-scenes/        Discovered/processed scene metadata
    retrieve: GET /api/satellite-scenes/{id}/   Single scene detail
    """

    queryset = SatelliteScene.objects.order_by("-acquisition_date")
    serializer_class = SatelliteSceneSerializer
    filterset_fields = ["source", "status", "provider"]
