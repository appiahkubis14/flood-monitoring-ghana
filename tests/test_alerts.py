"""
Tests for the alerts app: FloodEvent lifecycle, Alert/AlertRecipient
relationships, and CommunityReport verification workflow.

Run via Docker Compose: docker compose exec web pytest tests/test_alerts.py -v
"""
import pytest
from django.contrib.gis.geos import Point, Polygon
from django.utils import timezone

from apps.alerts.models import (
    Alert,
    AlertChannel,
    AlertDeliveryStatus,
    AlertRecipient,
    CommunityReport,
    FloodEvent,
)
from apps.core.models import SeverityLevel
from apps.satellite.models import FloodZone

pytestmark = pytest.mark.django_db

ODAW_BASIN_POLY = Polygon((
    (-0.22, 5.56), (-0.20, 5.56), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.56),
), srid=4326)


@pytest.fixture
def flood_zone() -> FloodZone:
    return FloodZone.objects.create(name="Odaw River Basin — Alajo", geometry=ODAW_BASIN_POLY)


class TestFloodEvent:
    def test_is_active_when_no_end_date(self, flood_zone):
        event = FloodEvent.objects.create(
            flood_zone=flood_zone, severity=SeverityLevel.ORANGE,
            triggered_by="sensor", started_at=timezone.now(),
        )
        assert event.is_active is True

    def test_is_active_false_once_resolved(self, flood_zone):
        event = FloodEvent.objects.create(
            flood_zone=flood_zone, severity=SeverityLevel.RED,
            triggered_by="combined", started_at=timezone.now(),
            ended_at=timezone.now(),
        )
        assert event.is_active is False


class TestAlertDelivery:
    def test_alert_has_uuid_for_external_reference(self, flood_zone):
        recipient = AlertRecipient.objects.create(full_name="Ama Owusu", phone_number="+233241234567")
        event = FloodEvent.objects.create(
            flood_zone=flood_zone, severity=SeverityLevel.RED,
            triggered_by="satellite", started_at=timezone.now(),
        )
        alert = Alert.objects.create(
            flood_event=event, recipient=recipient, severity=SeverityLevel.RED,
            channel=AlertChannel.WHATSAPP, message="Flood warning: evacuate now.",
        )
        assert alert.uuid is not None
        assert alert.delivery_status == AlertDeliveryStatus.PENDING

    def test_recipient_can_scope_to_specific_zones(self, flood_zone):
        recipient = AlertRecipient.objects.create(full_name="Kwame Asante", phone_number="+233201234567")
        recipient.flood_zones.add(flood_zone)
        assert flood_zone in recipient.flood_zones.all()


class TestCommunityReport:
    def test_unverified_by_default(self, flood_zone):
        report = CommunityReport.objects.create(
            location=Point(-0.21, 5.57, srid=4326),
            flood_zone=flood_zone, severity="moderate",
            reporter_phone="+233551234567",
        )
        assert report.is_verified is False

    def test_has_uuid_for_public_api_exposure(self, flood_zone):
        report = CommunityReport.objects.create(
            location=Point(-0.21, 5.57, srid=4326),
            flood_zone=flood_zone, severity="severe",
        )
        assert report.uuid is not None
