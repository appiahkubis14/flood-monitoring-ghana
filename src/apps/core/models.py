"""
Core abstract base models shared across the FloodWatch Ghana project.

Every domain model (sensors, satellite, alerts, dashboard) inherits from
``TimeStampedModel`` so created_at / updated_at are consistent and indexed
everywhere, instead of being re-declared (and potentially mis-declared) in
every app.
"""
from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding created_at / updated_at, both indexed.

    Using ``db_index=True`` on both timestamps because nearly every query in
    this project filters or orders by recency (latest sensor reading, most
    recent flood map, alerts in the last 24h, etc.).
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Abstract base for models that should expose a UUID instead of a raw
    sequential integer in public-facing APIs (e.g. community reports,
    alerts) -- avoids leaking record counts / enabling enumeration.
    """

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True


class SeverityLevel(models.TextChoices):
    """Shared 4-level severity scale used by FloodZone, Alert, and FloodEvent.

    Kept as a single shared choice set (rather than redefined per model) so
    the colour-coding logic (green/yellow/orange/red) in the dashboard and
    alert templates only has to be implemented once.
    """

    GREEN = "green", "Safe"
    YELLOW = "yellow", "Watch"
    ORANGE = "orange", "Warning"
    RED = "red", "Emergency"
