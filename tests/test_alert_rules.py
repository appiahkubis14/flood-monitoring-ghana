"""
Tests for the AlertRules engine: severity tiering, combined-source
escalation, and cooldown suppression.

Run via Docker Compose: docker compose exec web pytest tests/test_alert_rules.py -v
"""
import pytest
from django.contrib.gis.geos import Polygon
from django.utils import timezone

from apps.alerts.models import Alert, AlertChannel, AlertRecipient, FloodEvent
from apps.alerts.rules import AlertRules, max_severity, severity_rank
from apps.core.models import SeverityLevel
from apps.satellite.models import FloodZone

pytestmark = pytest.mark.django_db

ODAW_POLY = Polygon((
    (-0.22, 5.56), (-0.20, 5.56), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.56),
), srid=4326)


@pytest.fixture
def zone() -> FloodZone:
    return FloodZone.objects.create(
        name="Test Zone", geometry=ODAW_POLY,
        water_level_threshold_cm=50.0, rainfall_threshold_mm=40.0,
    )


class TestSeverityRank:
    def test_ordering(self):
        assert severity_rank(SeverityLevel.GREEN) < severity_rank(SeverityLevel.YELLOW)
        assert severity_rank(SeverityLevel.YELLOW) < severity_rank(SeverityLevel.ORANGE)
        assert severity_rank(SeverityLevel.ORANGE) < severity_rank(SeverityLevel.RED)

    def test_max_severity_picks_higher(self):
        assert max_severity(SeverityLevel.YELLOW, SeverityLevel.RED) == SeverityLevel.RED
        assert max_severity(SeverityLevel.RED, SeverityLevel.GREEN) == SeverityLevel.RED


class TestWaterLevelEvaluation:
    def test_below_yellow_is_green(self, zone):
        rules = AlertRules()
        result = rules.evaluate_water_level(10.0, zone)  # well below 70% of 50cm
        assert result.severity == SeverityLevel.GREEN
        assert result.triggered is False

    def test_at_zone_threshold_is_orange(self, zone):
        rules = AlertRules()
        result = rules.evaluate_water_level(50.0, zone)  # == orange threshold
        assert result.severity == SeverityLevel.ORANGE
        assert result.triggered is True

    def test_well_above_threshold_is_red(self, zone):
        rules = AlertRules()
        result = rules.evaluate_water_level(80.0, zone)  # 1.6x threshold > 1.5x red trigger
        assert result.severity == SeverityLevel.RED

    def test_no_zone_uses_global_default(self):
        rules = AlertRules()
        result = rules.evaluate_water_level(55.0, None)  # default orange=50
        assert result.severity == SeverityLevel.ORANGE


class TestRainfallEvaluation:
    def test_proportional_tiers(self, zone):
        rules = AlertRules()
        # zone.rainfall_threshold_mm = 40 -> yellow=28, orange=40, red=60
        assert rules.evaluate_rainfall(20.0, zone).severity == SeverityLevel.GREEN
        assert rules.evaluate_rainfall(30.0, zone).severity == SeverityLevel.YELLOW
        assert rules.evaluate_rainfall(40.0, zone).severity == SeverityLevel.ORANGE
        assert rules.evaluate_rainfall(65.0, zone).severity == SeverityLevel.RED


class TestSatelliteEvaluation:
    def test_no_area_not_triggered(self, zone):
        rules = AlertRules()
        result = rules.evaluate_satellite(0.0, 0.9, zone)
        assert result.triggered is False

    def test_low_confidence_capped_at_yellow(self, zone):
        rules = AlertRules()
        result = rules.evaluate_satellite(100.0, 0.3, zone)  # large area but low confidence
        assert result.severity == SeverityLevel.YELLOW

    def test_large_area_high_confidence_is_orange(self, zone):
        rules = AlertRules()
        result = rules.evaluate_satellite(60.0, 0.9, zone)
        assert result.severity == SeverityLevel.ORANGE


class TestCombine:
    def test_combined_sources_escalate_one_level(self, zone):
        rules = AlertRules()
        sensor = rules.evaluate_water_level(50.0, zone)   # ORANGE
        satellite = rules.evaluate_satellite(60.0, 0.9, zone)  # ORANGE
        combined = rules.combine(sensor, satellite)
        assert combined.severity == SeverityLevel.RED  # escalated by one level
        assert combined.triggered_by == "combined"

    def test_red_cannot_escalate_further(self, zone):
        rules = AlertRules()
        sensor = rules.evaluate_water_level(80.0, zone)  # RED
        satellite = rules.evaluate_satellite(60.0, 0.9, zone)  # ORANGE
        combined = rules.combine(sensor, satellite)
        assert combined.severity == SeverityLevel.RED  # capped, not overflowed

    def test_single_source_passthrough(self, zone):
        rules = AlertRules()
        sensor = rules.evaluate_water_level(55.0, zone)
        combined = rules.combine(sensor, None)
        assert combined == sensor

    def test_neither_triggered_returns_green(self, zone):
        rules = AlertRules()
        sensor = rules.evaluate_water_level(5.0, zone)
        satellite = rules.evaluate_satellite(0.0, 0.9, zone)
        combined = rules.combine(sensor, satellite)
        assert combined.severity == SeverityLevel.GREEN


class TestCooldown:
    def test_no_alerts_means_not_in_cooldown(self, zone):
        rules = AlertRules()
        assert rules.is_in_cooldown(zone, AlertChannel.WHATSAPP) is False

    def test_recent_alert_triggers_cooldown(self, zone):
        recipient = AlertRecipient.objects.create(full_name="Test", phone_number="+233200000000")
        event = FloodEvent.objects.create(
            flood_zone=zone, severity=SeverityLevel.ORANGE,
            triggered_by="sensor", started_at=timezone.now(),
        )
        Alert.objects.create(
            flood_event=event, recipient=recipient, severity=SeverityLevel.ORANGE,
            channel=AlertChannel.WHATSAPP, message="test",
        )
        rules = AlertRules()
        assert rules.is_in_cooldown(zone, AlertChannel.WHATSAPP) is True
        # Different channel for the same zone is independently NOT in cooldown.
        assert rules.is_in_cooldown(zone, AlertChannel.SMS) is False
