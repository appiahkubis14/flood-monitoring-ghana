"""URL routing for the alerts API."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertRecipientViewSet,
    AlertViewSet,
    CommunityReportViewSet,
    FloodEventViewSet,
    admin_broadcast_alert,
    admin_update_thresholds,
    subscribe_to_alerts,
    twilio_status_callback,
)

router = DefaultRouter()
router.register(r"alerts", AlertViewSet, basename="alert")
router.register(r"alert-recipients", AlertRecipientViewSet, basename="alert-recipient")
router.register(r"community-reports", CommunityReportViewSet, basename="community-report")
router.register(r"flood-events", FloodEventViewSet, basename="flood-event")

urlpatterns = router.urls + [
    path("alerts/subscribe/", subscribe_to_alerts, name="alerts-subscribe"),
    path("admin/alerts/broadcast/", admin_broadcast_alert, name="admin-alerts-broadcast"),
    path("admin/thresholds/", admin_update_thresholds, name="admin-thresholds"),
    path("webhooks/twilio/status/", twilio_status_callback, name="twilio-status-callback"),
]
