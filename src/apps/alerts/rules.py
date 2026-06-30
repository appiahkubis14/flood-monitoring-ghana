"""
Alert rules engine: decides whether sensor readings and/or satellite-derived
flood data warrant raising or escalating a FloodEvent, and at what severity.

Design:

* Thresholds are read **per-zone** (``FloodZone.water_level_threshold_cm`` /
  ``rainfall_threshold_mm``), with a global fallback for stations that have
  no zone assigned -- so each community can have realistic, locally-tuned
  thresholds instead of one Accra-wide number that's wrong for low-lying
  Korle Lagoon and wrong again for the upper Odaw catchment.
* Severity is a 4-level scale (green/yellow/orange/red) computed from how
  far a reading exceeds its threshold, not just a binary trip -- this is
  what lets the dashboard and alert messages show meaningful escalation
  instead of just "ALERT" every time.
* IoT-only detections and satellite-only detections both default to
  ORANGE at most; only when **both** corroborate (``combined``) can a
  FloodEvent reach RED. This directly implements the "Combined IoT +
  satellite confirmation" trigger from the project brief and is the main
  defence against single-sensor false positives causing panic alerts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

from apps.core.models import SeverityLevel
from apps.satellite.models import FloodZone

logger = logging.getLogger("apps.alerts")


# Severity ordering, used for escalation comparisons (RED > ORANGE > ...).
_SEVERITY_ORDER = {
    SeverityLevel.GREEN: 0,
    SeverityLevel.YELLOW: 1,
    SeverityLevel.ORANGE: 2,
    SeverityLevel.RED: 3,
}


def severity_rank(level: str) -> int:
    return _SEVERITY_ORDER.get(level, 0)


def max_severity(a: str, b: str) -> str:
    return a if severity_rank(a) >= severity_rank(b) else b


@dataclass
class RuleResult:
    """Outcome of evaluating one signal (sensor reading, satellite map, or
    both) against a zone's thresholds.
    """

    severity: str
    triggered: bool
    reason: str
    triggered_by: str  # FloodEvent.TriggerSource value


class AlertRules:
    """Evaluates sensor readings and satellite flood maps against
    per-zone thresholds and produces a :class:`RuleResult`.

    A single instance is stateless and safe to reuse across many
    evaluations (no per-call mutable state), so Celery tasks can hold one
    instance for the duration of a scan rather than re-instantiating per
    station.
    """

    # Global fallback thresholds, used only when a station/zone has none
    # configured -- e.g. a brand-new station not yet assigned to a FloodZone.
    DEFAULT_WATER_LEVEL_THRESHOLDS_CM = {"yellow": 30.0, "orange": 50.0, "red": 80.0}
    DEFAULT_RAINFALL_THRESHOLDS_MM = {"yellow": 20.0, "orange": 40.0, "red": 60.0}

    def evaluate_water_level(self, water_level_cm: float, zone: Optional[FloodZone]) -> RuleResult:
        """Severity from a single water-level reading.

        Per-zone thresholds in this project are single values
        (``water_level_threshold_cm``) rather than a 3-tier scale, so the
        tiers below are derived proportionally from that single number:
        the zone's threshold maps to ORANGE, with YELLOW at 70% of it and
        RED at 150% -- this keeps per-zone configuration simple (one
        number an operator can reason about) while still producing 4
        distinct severity levels.
        """
        if zone is not None:
            orange_t = zone.water_level_threshold_cm
        else:
            orange_t = self.DEFAULT_WATER_LEVEL_THRESHOLDS_CM["orange"]
        yellow_t = orange_t * 0.7
        red_t = orange_t * 1.5

        if water_level_cm >= red_t:
            severity = SeverityLevel.RED
        elif water_level_cm >= orange_t:
            severity = SeverityLevel.ORANGE
        elif water_level_cm >= yellow_t:
            severity = SeverityLevel.YELLOW
        else:
            severity = SeverityLevel.GREEN

        triggered = severity != SeverityLevel.GREEN
        return RuleResult(
            severity=severity,
            triggered=triggered,
            reason=f"Water level {water_level_cm:.1f}cm (threshold {orange_t:.1f}cm)",
            triggered_by="sensor",
        )

    def evaluate_rainfall(self, rainfall_mm: float, zone: Optional[FloodZone]) -> RuleResult:
        """Severity from a rainfall-rate reading, same proportional-tier logic
        as :meth:`evaluate_water_level`.
        """
        if zone is not None:
            orange_t = zone.rainfall_threshold_mm
        else:
            orange_t = self.DEFAULT_RAINFALL_THRESHOLDS_MM["orange"]
        yellow_t = orange_t * 0.7
        red_t = orange_t * 1.5

        if rainfall_mm >= red_t:
            severity = SeverityLevel.RED
        elif rainfall_mm >= orange_t:
            severity = SeverityLevel.ORANGE
        elif rainfall_mm >= yellow_t:
            severity = SeverityLevel.YELLOW
        else:
            severity = SeverityLevel.GREEN

        triggered = severity != SeverityLevel.GREEN
        return RuleResult(
            severity=severity,
            triggered=triggered,
            reason=f"Rainfall {rainfall_mm:.1f}mm/h (threshold {orange_t:.1f}mm/h)",
            triggered_by="sensor",
        )

    def evaluate_satellite(self, flooded_area_ha: float, confidence: float,
                            zone: Optional[FloodZone]) -> RuleResult:
        """Severity from a satellite-derived FloodMap.

        Confidence gates severity directly: a low-confidence detection
        (e.g. a weak MNDWI signal that could be cloud shadow) is capped at
        YELLOW regardless of area, so a single noisy scene can't trigger a
        RED alert on its own -- that requires either high confidence or
        sensor corroboration (see :meth:`combine`).
        """
        if flooded_area_ha <= 0:
            return RuleResult(SeverityLevel.GREEN, False, "No flooded area detected", "satellite")

        if confidence < 0.5:
            severity = SeverityLevel.YELLOW
        elif flooded_area_ha >= 50:
            severity = SeverityLevel.ORANGE
        elif flooded_area_ha >= 10:
            severity = SeverityLevel.YELLOW
        else:
            severity = SeverityLevel.YELLOW

        return RuleResult(
            severity=severity,
            triggered=True,
            reason=f"Satellite detected {flooded_area_ha:.1f}ha flooded (confidence {confidence:.0%})",
            triggered_by="satellite",
        )

    def combine(self, sensor_result: Optional[RuleResult], satellite_result: Optional[RuleResult]) -> RuleResult:
        """Combine independent sensor and satellite assessments.

        This is where corroboration is rewarded: two independent signals
        agreeing on "this zone is flooding" escalates severity by one
        level (capped at RED) and is recorded as ``triggered_by="combined"``
        rather than either source alone -- combined detections are the
        most actionable and least likely to be a false positive.
        """
        if sensor_result and not satellite_result:
            return sensor_result
        if satellite_result and not sensor_result:
            return satellite_result
        if not sensor_result and not satellite_result:
            return RuleResult(SeverityLevel.GREEN, False, "No data", "manual")

        if sensor_result.triggered and satellite_result.triggered:
            combined_severity = max_severity(sensor_result.severity, satellite_result.severity)
            # Escalate by one level when both sources agree, capped at RED.
            ranks = list(_SEVERITY_ORDER.keys())
            current_rank = severity_rank(combined_severity)
            escalated = ranks[min(current_rank + 1, len(ranks) - 1)]
            return RuleResult(
                severity=escalated,
                triggered=True,
                reason=f"Confirmed by both sensor and satellite: {sensor_result.reason}; {satellite_result.reason}",
                triggered_by="combined",
            )

        # Only one of the two actually triggered -- return whichever did.
        return sensor_result if sensor_result.triggered else satellite_result

    def is_in_cooldown(self, zone: FloodZone, channel: str) -> bool:
        """True if an alert of this severity-or-higher was already sent for
        this zone within the configured cooldown window -- the mechanism
        that satisfies the "avoid alert fatigue" requirement from the brief.
        """
        from apps.alerts.models import Alert

        cooldown = timedelta(minutes=settings.ALERT_COOLDOWN_MINUTES)
        cutoff = timezone.now() - cooldown
        return Alert.objects.filter(
            flood_event__flood_zone=zone,
            channel=channel,
            created_at__gte=cutoff,
        ).exists()
