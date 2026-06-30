"""URL routing for the sensors API."""
from rest_framework.routers import DefaultRouter

from .views import SensorReadingViewSet, SensorStationViewSet

router = DefaultRouter()
router.register(r"sensors", SensorStationViewSet, basename="sensor-station")
router.register(r"sensor-readings", SensorReadingViewSet, basename="sensor-reading")

urlpatterns = router.urls
