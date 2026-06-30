"""
Alert system models: flood events, alert records, recipient subscriptions,
and crowdsourced community reports.

The alert/event split is deliberate: a ``FloodEvent`` is the *thing that
happened* (a flood, tracked from detection to resolution), while ``Alert``
rows are the individual *notifications sent* about it -- one FloodEvent can
generate many Alerts (initial warning, escalation, all-clear) across
multiple recipients and channels.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.db import models

from apps.core.models import SeverityLevel, TimeStampedModel, UUIDModel


class FloodEvent(TimeStampedModel):
    """A tracked flood event from first detection to resolution.

    Deliberately decoupled from any single data source: ``triggered_by``
    records whether IoT, satellite, or both confirmed it, but the event
    itself is the unit of truth that the dashboard timeline and historical
    reports are built around.
    """

    class TriggerSource(models.TextChoices):
        SENSOR = "sensor", "IoT Sensor"
        SATELLITE = "satellite", "Satellite"
        COMBINED = "combined", "IoT + Satellite"
        COMMUNITY = "community", "Community Report"
        MANUAL = "manual", "Manual (Admin)"

    flood_zone = models.ForeignKey(
        "satellite.FloodZone", on_delete=models.CASCADE, related_name="flood_events"
    )
    severity = models.CharField(max_length=10, choices=SeverityLevel.choices, db_index=True)
    triggered_by = models.CharField(max_length=20, choices=TriggerSource.choices, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    affected_area_ha = models.FloatField(default=0.0)
    affected_area_geometry = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)
    peak_water_level_cm = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    related_flood_map = models.ForeignKey(
        "satellite.FloodMap", null=True, blank=True, on_delete=models.SET_NULL, related_name="flood_events"
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Flood Event"
        verbose_name_plural = "Flood Events"
        indexes = [
            models.Index(fields=["flood_zone", "-started_at"]),
        ]

    def __str__(self) -> str:
        status = "ongoing" if self.ended_at is None else "resolved"
        return f"{self.flood_zone.name} — {self.get_severity_display()} ({status})"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class AlertChannel(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    SMS = "sms", "SMS"
    EMAIL = "email", "Email"
    DASHBOARD = "dashboard", "Dashboard Only"


class AlertDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed (Cooldown)"


class Alert(UUIDModel, TimeStampedModel):
    """A single notification dispatched (or attempted) about a FloodEvent.

    ``uuid`` (from UUIDModel) is what's exposed in public-facing delivery
    receipts / webhook callbacks from Twilio, so internal primary keys are
    never leaked externally.
    """

    flood_event = models.ForeignKey(FloodEvent, on_delete=models.CASCADE, related_name="alerts")
    recipient = models.ForeignKey(
        "alerts.AlertRecipient", on_delete=models.CASCADE, related_name="alerts"
    )
    severity = models.CharField(max_length=10, choices=SeverityLevel.choices, db_index=True)
    channel = models.CharField(max_length=20, choices=AlertChannel.choices, db_index=True)
    message = models.TextField()
    delivery_status = models.CharField(
        max_length=20, choices=AlertDeliveryStatus.choices, default=AlertDeliveryStatus.PENDING, db_index=True
    )
    provider_message_id = models.CharField(
        max_length=100, blank=True, help_text="Twilio message SID, for delivery-status webhook matching"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Alert"
        verbose_name_plural = "Alerts"
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["flood_event", "channel"]),
        ]

    def __str__(self) -> str:
        return f"Alert[{self.get_severity_display()}] to {self.recipient} via {self.get_channel_display()}"


class AlertRecipient(TimeStampedModel):
    """A subscriber to flood alerts -- may or may not correspond to a
    registered ``User`` (community members can subscribe via phone number
    alone, without creating a login).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="alert_recipient"
    )
    full_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, db_index=True, help_text="E.164 format")
    preferred_channel = models.CharField(
        max_length=20, choices=AlertChannel.choices, default=AlertChannel.WHATSAPP
    )
    flood_zones = models.ManyToManyField(
        "satellite.FloodZone", blank=True, related_name="subscribers",
        help_text="Zones this recipient wants alerts for. Empty = all zones.",
    )
    min_severity = models.CharField(
        max_length=10, choices=SeverityLevel.choices, default=SeverityLevel.ORANGE,
        help_text="Only notify at or above this severity",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Alert Recipient"
        verbose_name_plural = "Alert Recipients"

    def __str__(self) -> str:
        return self.full_name or self.phone_number


class CommunityReport(UUIDModel, TimeStampedModel):
    """A crowdsourced flood report submitted by a citizen via the dashboard
    or a future mobile app.

    Kept deliberately simple and moderatable: ``is_verified`` lets a field
    officer promote a raw citizen report into something that can trigger
    (or corroborate) a FloodEvent, without auto-trusting unverified input.
    """

    class ReportSeverity(models.TextChoices):
        MINOR = "minor", "Minor — ankle deep"
        MODERATE = "moderate", "Moderate — knee deep"
        SEVERE = "severe", "Severe — waist deep or higher"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="community_reports"
    )
    reporter_phone = models.CharField(max_length=20, blank=True)
    location = gis_models.PointField(srid=4326)
    flood_zone = models.ForeignKey(
        "satellite.FloodZone", null=True, blank=True, on_delete=models.SET_NULL, related_name="community_reports"
    )
    severity = models.CharField(max_length=10, choices=ReportSeverity.choices)
    description = models.TextField(blank=True)
    photo = models.ImageField(upload_to="community_reports/%Y/%m/", null=True, blank=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_reports"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    related_flood_event = models.ForeignKey(
        FloodEvent, null=True, blank=True, on_delete=models.SET_NULL, related_name="community_reports"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Community Report"
        verbose_name_plural = "Community Reports"
        indexes = [
            models.Index(fields=["is_verified", "-created_at"]),
        ]

    def __str__(self) -> str:
        who = self.reporter or self.reporter_phone or "Anonymous"
        return f"Report by {who} — {self.get_severity_display()} ({self.created_at:%Y-%m-%d})"


class HistoricalFloodRecord(TimeStampedModel):
    """Historical flood records used for model training / trend analysis
    (e.g. digitised records of past Accra flood events from news/NADMO
    archives, pre-dating this system).
    """

    flood_zone = models.ForeignKey(
        "satellite.FloodZone", null=True, blank=True, on_delete=models.SET_NULL, related_name="historical_records"
    )
    event_date = models.DateField(db_index=True)
    severity = models.CharField(max_length=10, choices=SeverityLevel.choices)
    rainfall_mm = models.FloatField(null=True, blank=True)
    affected_area_ha = models.FloatField(null=True, blank=True)
    casualties = models.PositiveIntegerField(default=0)
    displaced_persons = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=200, blank=True, help_text="e.g. 'NADMO report 2023', 'GhanaWeb article'")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-event_date"]
        verbose_name = "Historical Flood Record"
        verbose_name_plural = "Historical Flood Records"

    def __str__(self) -> str:
        zone = self.flood_zone.name if self.flood_zone else "Accra"
        return f"{zone} flood — {self.event_date} ({self.get_severity_display()})"
