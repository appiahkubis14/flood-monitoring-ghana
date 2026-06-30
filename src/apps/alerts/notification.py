"""
Alert delivery via Twilio (WhatsApp primary, SMS fallback) and Django email
(admin notifications).

Design:

* Every send attempt is recorded as an :class:`Alert` row *before* the
  Twilio API call, with ``delivery_status=PENDING`` -- so a crash mid-send
  (network blip, worker killed) still leaves an auditable record instead of
  silently losing the attempt.
* WhatsApp is tried first; on failure (no WhatsApp-capable number, Twilio
  error, etc.) the same message is retried via SMS automatically when the
  recipient's ``preferred_channel`` is WhatsApp -- this directly implements
  the "WhatsApp primary, SMS fallback" requirement rather than just letting
  the WhatsApp attempt fail silently.
* Twilio's client is constructed lazily and only once real credentials are
  present, so importing this module (and running the test suite) never
  requires real Twilio credentials or makes network calls.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import mail_admins
from django.utils import timezone

if TYPE_CHECKING:
    from apps.alerts.models import Alert

logger = logging.getLogger("apps.alerts")


class TwilioNotConfigured(RuntimeError):
    """Raised when a Twilio send is attempted without credentials set."""


def _get_twilio_client():
    """Lazily construct the Twilio client. Raises TwilioNotConfigured rather
    than letting the twilio library raise its own (less clear) error when
    credentials are blank -- common in development environments where
    Twilio isn't wired up yet.
    """
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise TwilioNotConfigured(
            "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set. "
            "Set them in .env to enable WhatsApp/SMS delivery."
        )
    from twilio.rest import Client

    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_whatsapp(to_phone: str, message: str) -> str:
    """Send a WhatsApp message via Twilio. Returns the provider message SID.

    ``to_phone`` must be E.164 (e.g. ``+233241234567``); the ``whatsapp:``
    prefix required by Twilio's API is added here so callers never need to
    know about that formatting detail.
    """
    client = _get_twilio_client()
    result = client.messages.create(
        from_=settings.TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{to_phone}",
        body=message,
    )
    return result.sid


def send_sms(to_phone: str, message: str) -> str:
    """Send an SMS via Twilio. Returns the provider message SID."""
    client = _get_twilio_client()
    result = client.messages.create(
        from_=settings.TWILIO_SMS_FROM,
        to=to_phone,
        body=message,
    )
    return result.sid


def deliver_alert(alert: "Alert") -> None:
    """Deliver a single :class:`Alert` row via its channel, with automatic
    WhatsApp -> SMS fallback, updating ``delivery_status`` / timestamps /
    ``provider_message_id`` / ``error_message`` on the row as it goes.

    This is the single entry point Celery tasks should call -- it never
    raises (failures are recorded on the Alert row instead) so a bad phone
    number for one recipient can't crash a batch send for everyone else.
    """
    from apps.alerts.models import AlertChannel, AlertDeliveryStatus

    recipient_phone = alert.recipient.phone_number

    try:
        if alert.channel == AlertChannel.WHATSAPP:
            try:
                sid = send_whatsapp(recipient_phone, alert.message)
                _mark_sent(alert, sid)
                return
            except TwilioNotConfigured:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "WhatsApp delivery failed for alert %s (%s); falling back to SMS",
                    alert.uuid, exc,
                )
                sid = send_sms(recipient_phone, alert.message)
                alert.channel = AlertChannel.SMS  # record what actually delivered
                _mark_sent(alert, sid)
                return

        elif alert.channel == AlertChannel.SMS:
            sid = send_sms(recipient_phone, alert.message)
            _mark_sent(alert, sid)
            return

        elif alert.channel == AlertChannel.EMAIL:
            mail_admins(
                subject=f"FloodWatch Alert [{alert.get_severity_display()}]",
                message=alert.message,
            )
            _mark_sent(alert, provider_message_id="")
            return

        else:  # DASHBOARD -- no external delivery, just mark as delivered
            alert.delivery_status = AlertDeliveryStatus.DELIVERED
            alert.sent_at = timezone.now()
            alert.delivered_at = timezone.now()
            alert.save(update_fields=["delivery_status", "sent_at", "delivered_at"])
            return

    except TwilioNotConfigured as exc:
        logger.error("Cannot deliver alert %s: %s", alert.uuid, exc)
        alert.delivery_status = AlertDeliveryStatus.FAILED
        alert.error_message = str(exc)
        alert.save(update_fields=["delivery_status", "error_message"])

    except Exception as exc:  # noqa: BLE001 -- never let a bad number crash the batch
        logger.exception("Unexpected error delivering alert %s", alert.uuid)
        alert.delivery_status = AlertDeliveryStatus.FAILED
        alert.error_message = str(exc)
        alert.save(update_fields=["delivery_status", "error_message"])


def _mark_sent(alert: "Alert", provider_message_id: str) -> None:
    from apps.alerts.models import AlertDeliveryStatus

    alert.delivery_status = AlertDeliveryStatus.SENT
    alert.provider_message_id = provider_message_id
    alert.sent_at = timezone.now()
    alert.save(update_fields=["delivery_status", "channel", "provider_message_id", "sent_at"])


def handle_twilio_status_callback(message_sid: str, status: str) -> bool:
    """Update an Alert's delivery_status from a Twilio status callback webhook.

    Returns True if a matching Alert was found and updated, False otherwise
    (e.g. the webhook arrived for a message this system didn't send, or
    arrived after the Alert row was deleted).
    """
    from apps.alerts.models import Alert, AlertDeliveryStatus

    status_map = {
        "delivered": AlertDeliveryStatus.DELIVERED,
        "sent": AlertDeliveryStatus.SENT,
        "failed": AlertDeliveryStatus.FAILED,
        "undelivered": AlertDeliveryStatus.FAILED,
    }
    new_status = status_map.get(status)
    if new_status is None:
        return False

    updated = Alert.objects.filter(provider_message_id=message_sid).update(
        delivery_status=new_status,
        delivered_at=timezone.now() if new_status == AlertDeliveryStatus.DELIVERED else None,
    )
    return updated > 0
