"""
API views for the alerts app.

Implements, from the project brief:
  GET    /api/alerts/                 List recent alerts
  POST   /api/community-reports/      Submit community flood report
  POST   /api/admin/alerts/broadcast  Send manual alert
  PUT    /api/admin/thresholds/       Update alert thresholds

Plus a public self-service subscription endpoint
(``POST /api/alerts/subscribe/``) that wasn't explicitly itemised in the
brief's endpoint table but is required to make "community members can
subscribe to alerts" actually possible without an admin doing it manually
for every resident.
"""
from __future__ import annotations

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.sensors.views import IsAdminOrReadOnly

from .models import Alert, AlertRecipient, CommunityReport, FloodEvent
from .serializers import (
    AlertRecipientSerializer,
    AlertRecipientSubscribeSerializer,
    AlertSerializer,
    CommunityReportCreateSerializer,
    CommunityReportSerializer,
    FloodEventSerializer,
)


class FloodEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/flood-events/         All flood events, most recent first
    retrieve: GET /api/flood-events/{id}/    Single event detail
    """

    queryset = FloodEvent.objects.select_related("flood_zone").order_by("-started_at")
    serializer_class = FloodEventSerializer
    filterset_fields = ["flood_zone", "severity", "triggered_by"]


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    list:     GET /api/alerts/          Recent alerts (admin sees all; others see their own)
    retrieve: GET /api/alerts/{id}/
    """

    serializer_class = AlertSerializer
    filterset_fields = ["severity", "channel", "delivery_status"]
    lookup_field = "uuid"

    def get_queryset(self):
        qs = Alert.objects.select_related("recipient", "flood_event").order_by("-created_at")
        user = self.request.user
        if user.is_authenticated and user.is_staff:
            return qs
        if user.is_authenticated and hasattr(user, "alert_recipient"):
            return qs.filter(recipient=user.alert_recipient)
        return qs.none()


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def subscribe_to_alerts(request):
    """POST /api/alerts/subscribe/ -- public self-service subscription.
    No authentication required: a community member only needs to provide
    a phone number to start receiving flood alerts for their area.
    """
    serializer = AlertRecipientSubscribeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    recipient = serializer.save()
    return Response(
        AlertRecipientSerializer(recipient).data, status=status.HTTP_201_CREATED
    )


class AlertRecipientViewSet(viewsets.ModelViewSet):
    """Admin-only management of alert recipients (view/edit/deactivate)."""

    queryset = AlertRecipient.objects.prefetch_related("flood_zones").all()
    serializer_class = AlertRecipientSerializer
    permission_classes = [permissions.IsAdminUser]


class CommunityReportViewSet(viewsets.ModelViewSet):
    """
    list:     GET  /api/community-reports/         List reports (public)
    retrieve: GET  /api/community-reports/{uuid}/
    create:   POST /api/community-reports/          Submit a report (public, no auth required)
    verify:   POST /api/community-reports/{uuid}/verify/   Mark verified (field officer/admin only)
    """

    queryset = CommunityReport.objects.select_related("reporter", "flood_zone").order_by("-created_at")
    lookup_field = "uuid"
    filterset_fields = ["is_verified", "flood_zone", "severity"]

    def get_permissions(self):
        if self.action in ("create",):
            return [permissions.AllowAny()]
        if self.action in ("update", "partial_update", "destroy", "verify"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self):
        if self.action == "create":
            return CommunityReportCreateSerializer
        return CommunityReportSerializer

    def perform_create(self, serializer):
        report = serializer.save()
        # A SEVERE community report is itself a corroborating signal worth
        # immediately checking against the zone's active FloodEvent state,
        # same as a sensor threshold breach would be.
        if report.severity == "severe" and report.flood_zone is not None:
            from apps.alerts.tasks import create_and_send_alerts

            event = FloodEvent.objects.filter(
                flood_zone=report.flood_zone, ended_at__isnull=True
            ).first()
            created = False
            if event is None:
                event = FloodEvent.objects.create(
                    flood_zone=report.flood_zone,
                    severity="orange",
                    triggered_by="community",
                    started_at=report.created_at,
                )
                created = True
            if created:
                create_and_send_alerts.delay(event.id)
            report.related_flood_event = event
            report.save(update_fields=["related_flood_event"])

    @action(detail=True, methods=["post"])
    def verify(self, request, uuid=None):
        from django.utils import timezone

        report = self.get_object()
        report.is_verified = True
        report.verified_by = request.user
        report.verified_at = timezone.now()
        report.save(update_fields=["is_verified", "verified_by", "verified_at"])
        return Response(CommunityReportSerializer(report).data)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def admin_broadcast_alert(request):
    """POST /api/admin/alerts/broadcast -- operator-initiated message,
    not tied to a newly-detected FloodEvent (e.g. "shelter open at the
    community centre"). See ``apps.alerts.tasks.send_community_broadcast``.
    """
    from .tasks import send_community_broadcast

    message = request.data.get("message")
    if not message:
        return Response({"detail": "message is required"}, status=400)
    severity = request.data.get("severity", "orange")
    zone_id = request.data.get("zone_id")

    task = send_community_broadcast.delay(message, severity, zone_id)
    return Response({"task_id": task.id, "status": "queued"}, status=202)


@api_view(["PUT"])
@permission_classes([permissions.IsAdminUser])
def admin_update_thresholds(request):
    """PUT /api/admin/thresholds/ -- update a FloodZone's water-level /
    rainfall thresholds. Body: {"zone_id": <int>, "water_level_threshold_cm":
    <float>, "rainfall_threshold_mm": <float>}.
    """
    from apps.satellite.models import FloodZone

    zone_id = request.data.get("zone_id")
    if not zone_id:
        return Response({"detail": "zone_id is required"}, status=400)
    try:
        zone = FloodZone.objects.get(pk=zone_id)
    except FloodZone.DoesNotExist:
        return Response({"detail": "Zone not found"}, status=404)

    update_fields = []
    if "water_level_threshold_cm" in request.data:
        zone.water_level_threshold_cm = float(request.data["water_level_threshold_cm"])
        update_fields.append("water_level_threshold_cm")
    if "rainfall_threshold_mm" in request.data:
        zone.rainfall_threshold_mm = float(request.data["rainfall_threshold_mm"])
        update_fields.append("rainfall_threshold_mm")

    if not update_fields:
        return Response({"detail": "No threshold fields provided"}, status=400)

    zone.save(update_fields=update_fields)
    return Response({
        "zone_id": zone.id,
        "water_level_threshold_cm": zone.water_level_threshold_cm,
        "rainfall_threshold_mm": zone.rainfall_threshold_mm,
    })


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def twilio_status_callback(request):
    """POST /api/webhooks/twilio/status/ -- Twilio delivery-status webhook.

    Twilio calls this URL itself (not authenticated as a Django user), so
    permission is AllowAny -- the only validation performed is checking
    that ``MessageSid`` corresponds to an Alert this system actually sent;
    unmatched callbacks are silently ignored rather than erroring, since a
    misdirected or replayed webhook from Twilio's side shouldn't be able to
    return a 500 to their retry logic.
    """
    from apps.alerts.notification import handle_twilio_status_callback

    message_sid = request.data.get("MessageSid")
    status_value = request.data.get("MessageStatus")
    if not message_sid or not status_value:
        return Response({"detail": "MessageSid and MessageStatus are required"}, status=400)

    handle_twilio_status_callback(message_sid, status_value)
    return Response(status=204)
