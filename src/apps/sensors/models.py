"""
IoT sensor models: physical stations (ESP32 units) and their readings.

Design notes:

* ``SensorStation.location`` is a PostGIS ``PointField`` so we can do
  proper geospatial queries (nearest station to a flood polygon, stations
  within a FloodZone, etc.) rather than storing lat/lon as plain floats.
* ``SensorReading`` is intentionally a high-volume, append-only table:
  no FKs back to it from other tables, indexed on (station, timestamp) for
  the two query patterns that matter -- "latest reading for station X" and
  "all readings for station X in time range Y".
* Status is derived (see ``SensorStation.refresh_status``) rather than set
  by the ingestion pipeline directly, so a single source of truth exists for
  "is this sensor online" instead of every caller reimplementing the
  staleness check.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class StationStatus(models.TextChoices):
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"
    MAINTENANCE = "maintenance", "Under Maintenance"
    FAULTY = "faulty", "Faulty"


class SensorStation(TimeStampedModel):
    """A physical ESP32-based monitoring station with water level + rain gauge."""

    name = models.CharField(max_length=100)
    location = gis_models.PointField(srid=4326, help_text="WGS84 lon/lat of the station")
    community = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Local community / neighbourhood name, e.g. 'Alajo', 'Agbogbloshie'",
    )
    status = models.CharField(
        max_length=20, choices=StationStatus.choices, default=StationStatus.OFFLINE, db_index=True
    )
    installed_date = models.DateTimeField(auto_now_add=True)
    last_reading_at = models.DateTimeField(null=True, blank=True, db_index=True)
    battery_level = models.FloatField(default=100.0, help_text="Percent, 0-100")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    serial_number = models.CharField(max_length=50, unique=True, db_index=True)
    flood_zone = models.ForeignKey(
        "satellite.FloodZone", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stations",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Sensor Station"
        verbose_name_plural = "Sensor Stations"
        indexes = [
            models.Index(fields=["status", "last_reading_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.serial_number})"

    @property
    def is_stale(self) -> bool:
        """True when the station hasn't reported within the configured window."""
        if self.last_reading_at is None:
            return True
        threshold = timedelta(minutes=settings.SENSOR_OFFLINE_THRESHOLD_MINUTES)
        return timezone.now() - self.last_reading_at > threshold

    def refresh_status(self, save: bool = True) -> str:
        """Recompute ``status`` from staleness. Does not override
        MAINTENANCE/FAULTY, which are set explicitly by an operator.
        """
        if self.status in (StationStatus.MAINTENANCE, StationStatus.FAULTY):
            return self.status
        new_status = StationStatus.OFFLINE if self.is_stale else StationStatus.ONLINE
        if new_status != self.status:
            self.status = new_status
            if save:
                self.save(update_fields=["status"])
        return self.status

    def latest_reading(self) -> "SensorReading | None":
        return self.readings.order_by("-timestamp").first()


class SensorReading(TimeStampedModel):
    """A single telemetry sample from a station.

    High write volume -- kept lean (no FKs pointing *into* this table) and
    indexed for the (station, timestamp) access pattern used by both the
    dashboard ("last 24h for this station") and the alert rules engine
    ("most recent reading").
    """

    station = models.ForeignKey(SensorStation, on_delete=models.CASCADE, related_name="readings")
    water_level_cm = models.FloatField(help_text="Water level above the gauge datum, in cm")
    rainfall_mm = models.FloatField(help_text="Rainfall accumulated since last reading, in mm")
    temperature_c = models.FloatField(null=True, blank=True)
    battery_voltage = models.FloatField(null=True, blank=True)
    signal_strength = models.IntegerField(null=True, blank=True, help_text="RSSI, dBm")
    timestamp = models.DateTimeField(db_index=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Set True once the reading has passed range/rate-of-change validation",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Sensor Reading"
        verbose_name_plural = "Sensor Readings"
        indexes = [
            models.Index(fields=["station", "-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.station.name} @ {self.timestamp:%Y-%m-%d %H:%M} — {self.water_level_cm}cm"
