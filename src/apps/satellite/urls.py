"""URL routing for the satellite API."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    FloodMapViewSet,
    FloodZoneViewSet,
    SatelliteSceneViewSet,
    trigger_satellite_run,
)

router = DefaultRouter()
router.register(r"flood-zones", FloodZoneViewSet, basename="flood-zone")
router.register(r"flood-maps", FloodMapViewSet, basename="flood-map")
router.register(r"satellite-scenes", SatelliteSceneViewSet, basename="satellite-scene")

urlpatterns = router.urls + [
    path("admin/satellite/run/", trigger_satellite_run, name="admin-satellite-run"),
]
