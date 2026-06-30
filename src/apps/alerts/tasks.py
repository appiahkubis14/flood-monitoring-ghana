"""
Celery tasks for the alerts app: dispatching notifications, generating
daily reports, and the community broadcast task.

``create_and_send_alerts`` is the single fan-out point used by both the
sensor threshold checker (``apps.sensors.tasks.check_sensor_thresholds``)
and the satellite pipeline (``apps.satellite.tasks.process_satellite_data``)
-- both call into this one function rather than duplicating recipient
lookup / cooldown / delivery logic in two places.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.alerts.notification import deliver_alert
from apps.alerts.rules import AlertRules

logger = logging.getLogger("apps.alerts")


def _severity_meets_threshold(severity: str, min_severity: str) -> bool:
    from apps.alerts.rules import severity_rank
    return severity_rank(severity) >= severity_rank(min_severity)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def create_and_send_alerts(self, flood_event_id: int) -> dict:
    """Fan out a FloodEvent to every eligible AlertRecipient.

    Eligibility: recipient is active, subscribed to this zone (or to no
    specific zone, meaning "all zones"), and the event's severity meets or
    exceeds the recipient's configured ``min_severity``. Cooldown is
    checked per (zone, channel) so a flapping sensor near a threshold
    can't spam the same channel repeatedly within
    ``settings.ALERT_COOLDOWN_MINUTES``.
    """
    from apps.alerts.models import Alert, AlertRecipient, FloodEvent

    try:
        event = FloodEvent.objects.select_related("flood_zone").get(pk=flood_event_id)
    except FloodEvent.DoesNotExist:
        logger.error("create_and_send_alerts: FloodEvent %s not found", flood_event_id)
        return {"sent": 0, "skipped": 0, "error": "event_not_found"}

    rules = AlertRules()
    recipients = AlertRecipient.objects.filter(is_active=True).prefetch_related("flood_zones")

    sent, skipped, suppressed = 0, 0, 0
    for recipient in recipients:
        zones = list(recipient.flood_zones.all())
        if zones and event.flood_zone not in zones:
            skipped += 1
            continue
        if not _severity_meets_threshold(event.severity, recipient.min_severity):
            skipped += 1
            continue

        if rules.is_in_cooldown(event.flood_zone, recipient.preferred_channel):
            logger.info(
                "Cooldown active for zone=%s channel=%s; suppressing alert to %s",
                event.flood_zone, recipient.preferred_channel, recipient,
            )
            Alert.objects.create(
                flood_event=event, recipient=recipient, severity=event.severity,
                channel=recipient.preferred_channel,
                message=_build_message(event),
                delivery_status="suppressed",
            )
            suppressed += 1
            continue

        alert = Alert.objects.create(
            flood_event=event, recipient=recipient, severity=event.severity,
            channel=recipient.preferred_channel, message=_build_message(event),
        )
        send_alert.delay(alert.id)
        sent += 1

    logger.info(
        "FloodEvent %s: dispatched=%d skipped=%d suppressed=%d",
        flood_event_id, sent, skipped, suppressed,
    )
    return {"sent": sent, "skipped": skipped, "suppressed": suppressed}


def _build_message(event) -> str:
    """Build the human-readable alert text.

    Kept short and action-oriented for SMS-length constraints (160 chars
    is the classic single-SMS limit) even though WhatsApp doesn't need it
    -- using the same message for both channels keeps delivery logic
    simple and the SMS fallback path (see notification.deliver_alert)
    never needs a second message variant.
    """
    severity_label = event.get_severity_display().upper()
    zone_name = event.flood_zone.name
    return (
        f"[FloodWatch Ghana — {severity_label}] Flooding detected in {zone_name}. "
        f"Triggered by: {event.get_triggered_by_display()}. "
        f"Stay alert, avoid the area, and follow guidance from local authorities."
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def send_alert(self, alert_id: int) -> None:
    """Deliver a single previously-created Alert row (WhatsApp/SMS/Email),
    and push it to connected dashboard clients over the ``alerts_live``
    WebSocket group regardless of external delivery outcome -- the
    dashboard bell/feed should show a new alert immediately even if the
    WhatsApp/SMS send to a phone number is still in flight or fails.
    """
    from apps.alerts.models import Alert

    try:
        alert = Alert.objects.select_related("recipient", "flood_event").get(pk=alert_id)
    except Alert.DoesNotExist:
        logger.error("send_alert: Alert %s not found", alert_id)
        return
    deliver_alert(alert)
    _broadcast_alert(alert)


def _broadcast_alert(alert) -> None:
    """Push a newly created/delivered Alert to the ``alerts_live``
    WebSocket group (see ``apps.sensors.consumers.AlertConsumer``).
    Swallows channel-layer errors -- a Redis blip must not fail alert
    delivery, which is already complete by the time this is called.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            "alerts_live",
            {
                "type": "alert.created",
                "payload": {
                    "alert_uuid": str(alert.uuid),
                    "severity": alert.severity,
                    "channel": alert.channel,
                    "message": alert.message,
                    "delivery_status": alert.delivery_status,
                    "zone": alert.flood_event.flood_zone.name,
                    "created_at": alert.created_at.isoformat(),
                },
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to broadcast alert over WebSocket")


@shared_task
def send_community_broadcast(message: str, severity: str = "orange", zone_id: int | None = None) -> dict:
    """Manually triggered broadcast (admin API: POST /api/admin/alerts/broadcast).

    Unlike ``create_and_send_alerts``, this is not tied to a FloodEvent --
    it's for operator-initiated messages ("road closed", "shelter open at
    X", etc.) that don't represent a new detected flood.
    """
    from apps.alerts.models import Alert, AlertRecipient, FloodEvent
    from apps.satellite.models import FloodZone

    recipients = AlertRecipient.objects.filter(is_active=True)
    if zone_id is not None:
        zone = FloodZone.objects.filter(pk=zone_id).first()
        if zone is None:
            return {"sent": 0, "error": "zone_not_found"}
        recipients = recipients.filter(flood_zones=zone) | recipients.filter(flood_zones__isnull=True)
        recipients = recipients.distinct()

    sent = 0
    for recipient in recipients:
        # Manual broadcasts use a placeholder FloodEvent-less Alert: the FK
        # is required, so callers triggering this without an active event
        # should create one first (see admin view) -- enforced there, not here.
        event = FloodEvent.objects.filter(
            flood_zone_id=zone_id, ended_at__isnull=True
        ).first() if zone_id else FloodEvent.objects.filter(ended_at__isnull=True).first()
        if event is None:
            continue
        alert = Alert.objects.create(
            flood_event=event, recipient=recipient, severity=severity,
            channel=recipient.preferred_channel, message=message,
        )
        send_alert.delay(alert.id)
        sent += 1

    return {"sent": sent}


@shared_task
def generate_daily_report() -> dict:
    """Build a daily flood-monitoring summary: active events, alerts sent,
    new community reports, sensor uptime. Emails it to admins.

    Intended to run once every 24h via Celery beat (see
    ``CELERY_BEAT_SCHEDULE['generate-daily-report']`` in settings).
    """
    from datetime import timedelta

    from django.core.mail import mail_admins

    from apps.alerts.models import Alert, CommunityReport, FloodEvent
    from apps.sensors.models import SensorStation

    since = timezone.now() - timedelta(hours=24)

    active_events = FloodEvent.objects.filter(ended_at__isnull=True).select_related("flood_zone")
    new_events_24h = FloodEvent.objects.filter(started_at__gte=since).count()
    alerts_24h = Alert.objects.filter(created_at__gte=since)
    new_reports_24h = CommunityReport.objects.filter(created_at__gte=since).count()
    unverified_reports = CommunityReport.objects.filter(is_verified=False).count()

    total_stations = SensorStation.objects.count()
    online_stations = SensorStation.objects.filter(status="online").count()

    lines = [
        f"FloodWatch Ghana — Daily Report ({timezone.now():%Y-%m-%d})",
        "=" * 50,
        f"Active flood events: {active_events.count()}",
    ]
    for event in active_events:
        lines.append(f"  - {event.flood_zone.name}: {event.get_severity_display()} (since {event.started_at:%Y-%m-%d %H:%M})")

    lines += [
        f"\nNew events in last 24h: {new_events_24h}",
        f"Alerts sent in last 24h: {alerts_24h.count()}",
        f"  delivered: {alerts_24h.filter(delivery_status='delivered').count()}",
        f"  failed: {alerts_24h.filter(delivery_status='failed').count()}",
        f"\nCommunity reports (24h): {new_reports_24h}  (unverified total: {unverified_reports})",
        f"\nSensor network: {online_stations}/{total_stations} stations online",
    ]
    report_text = "\n".join(lines)

    mail_admins(subject="FloodWatch Ghana — Daily Report", message=report_text)
    logger.info("Daily report generated and emailed to admins")
    return {"active_events": active_events.count(), "alerts_sent_24h": alerts_24h.count()}
