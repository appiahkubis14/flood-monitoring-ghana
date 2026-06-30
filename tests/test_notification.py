"""
Tests for the Twilio notification module -- WhatsApp->SMS fallback and
delivery status tracking. Twilio's API itself is mocked throughout; no
real network calls or credentials are required to run these.

Run via Docker Compose: docker compose exec web pytest tests/test_notification.py -v
"""
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import Polygon
from django.utils import timezone

from apps.alerts.models import Alert, AlertChannel, AlertDeliveryStatus, AlertRecipient, FloodEvent
from apps.alerts.notification import TwilioNotConfigured, deliver_alert, handle_twilio_status_callback
from apps.core.models import SeverityLevel
from apps.satellite.models import FloodZone

pytestmark = pytest.mark.django_db

ODAW_POLY = Polygon((
    (-0.22, 5.56), (-0.20, 5.56), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.56),
), srid=4326)


@pytest.fixture
def alert() -> Alert:
    zone = FloodZone.objects.create(name="Test Zone", geometry=ODAW_POLY)
    recipient = AlertRecipient.objects.create(full_name="Ama", phone_number="+233241234567")
    event = FloodEvent.objects.create(
        flood_zone=zone, severity=SeverityLevel.RED, triggered_by="sensor", started_at=timezone.now(),
    )
    return Alert.objects.create(
        flood_event=event, recipient=recipient, severity=SeverityLevel.RED,
        channel=AlertChannel.WHATSAPP, message="Flood warning",
    )


class TestDeliverAlertWithoutCredentials:
    def test_marks_failed_when_twilio_not_configured(self, alert, settings):
        settings.TWILIO_ACCOUNT_SID = ""
        settings.TWILIO_AUTH_TOKEN = ""
        deliver_alert(alert)
        alert.refresh_from_db()
        assert alert.delivery_status == AlertDeliveryStatus.FAILED
        assert "TWILIO_ACCOUNT_SID" in alert.error_message


class TestWhatsAppToSmsFallback:
    @patch("apps.alerts.notification.send_sms")
    @patch("apps.alerts.notification.send_whatsapp")
    def test_falls_back_to_sms_on_whatsapp_failure(self, mock_whatsapp, mock_sms, alert, settings):
        settings.TWILIO_ACCOUNT_SID = "test_sid"
        settings.TWILIO_AUTH_TOKEN = "test_token"
        mock_whatsapp.side_effect = Exception("No WhatsApp-enabled number")
        mock_sms.return_value = "SM_fake_sid_123"

        deliver_alert(alert)

        mock_whatsapp.assert_called_once()
        mock_sms.assert_called_once()
        alert.refresh_from_db()
        assert alert.channel == AlertChannel.SMS  # fallback recorded what actually delivered
        assert alert.delivery_status == AlertDeliveryStatus.SENT
        assert alert.provider_message_id == "SM_fake_sid_123"

    @patch("apps.alerts.notification.send_whatsapp")
    def test_no_fallback_needed_when_whatsapp_succeeds(self, mock_whatsapp, alert, settings):
        settings.TWILIO_ACCOUNT_SID = "test_sid"
        settings.TWILIO_AUTH_TOKEN = "test_token"
        mock_whatsapp.return_value = "WA_fake_sid_456"

        deliver_alert(alert)

        alert.refresh_from_db()
        assert alert.channel == AlertChannel.WHATSAPP
        assert alert.delivery_status == AlertDeliveryStatus.SENT
        assert alert.provider_message_id == "WA_fake_sid_456"


class TestSmsDirectChannel:
    @patch("apps.alerts.notification.send_sms")
    def test_sms_channel_does_not_attempt_whatsapp(self, mock_sms, alert, settings):
        settings.TWILIO_ACCOUNT_SID = "test_sid"
        settings.TWILIO_AUTH_TOKEN = "test_token"
        alert.channel = AlertChannel.SMS
        alert.save()
        mock_sms.return_value = "SM_direct_789"

        deliver_alert(alert)

        alert.refresh_from_db()
        assert alert.delivery_status == AlertDeliveryStatus.SENT
        assert alert.provider_message_id == "SM_direct_789"


class TestDashboardChannel:
    def test_dashboard_channel_marks_delivered_with_no_external_call(self, alert):
        alert.channel = AlertChannel.DASHBOARD
        alert.save()
        deliver_alert(alert)
        alert.refresh_from_db()
        assert alert.delivery_status == AlertDeliveryStatus.DELIVERED


class TestStatusCallback:
    def test_updates_matching_alert(self, alert):
        alert.provider_message_id = "SM_callback_test"
        alert.save()
        updated = handle_twilio_status_callback("SM_callback_test", "delivered")
        assert updated is True
        alert.refresh_from_db()
        assert alert.delivery_status == AlertDeliveryStatus.DELIVERED

    def test_no_match_returns_false(self):
        updated = handle_twilio_status_callback("SM_does_not_exist", "delivered")
        assert updated is False

    def test_unknown_status_value_returns_false(self, alert):
        alert.provider_message_id = "SM_unknown_status"
        alert.save()
        updated = handle_twilio_status_callback("SM_unknown_status", "some_unrecognised_status")
        assert updated is False
