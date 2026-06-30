"""
Tests for MQTT-driven sensor ingestion: payload validation and the
ingest_sensor_reading task's effects on SensorStation/SensorReading state.

Run via Docker Compose: docker compose exec web pytest tests/test_sensor_ingestion.py -v
"""
import pytest
from django.contrib.gis.geos import Point

from apps.sensors.models import SensorReading, SensorStation, StationStatus
from apps.sensors.tasks import _validate_reading_payload, ingest_sensor_reading

pytestmark = pytest.mark.django_db


class TestPayloadValidation:
    def test_valid_payload_passes(self):
        result = _validate_reading_payload({"water_level_cm": 25.0, "rainfall_mm": 5.0})
        assert result["valid"] is True

    def test_missing_required_field_rejected(self):
        result = _validate_reading_payload({"water_level_cm": 25.0})
        assert result["valid"] is False
        assert "missing" in result["reason"]

    def test_negative_water_level_rejected(self):
        result = _validate_reading_payload({"water_level_cm": -5.0, "rainfall_mm": 0.0})
        assert result["valid"] is False

    def test_implausibly_high_water_level_rejected(self):
        result = _validate_reading_payload({"water_level_cm": 99999.0, "rainfall_mm": 0.0})
        assert result["valid"] is False

    def test_non_numeric_rejected(self):
        result = _validate_reading_payload({"water_level_cm": "not-a-number", "rainfall_mm": 0.0})
        assert result["valid"] is False

    def test_implausible_temperature_rejected(self):
        result = _validate_reading_payload({
            "water_level_cm": 10.0, "rainfall_mm": 0.0, "temperature_c": 200.0,
        })
        assert result["valid"] is False

    def test_temperature_optional(self):
        result = _validate_reading_payload({"water_level_cm": 10.0, "rainfall_mm": 0.0})
        assert result["valid"] is True


class TestIngestSensorReading:
    def test_unknown_station_ignored(self):
        result = ingest_sensor_reading("DOES-NOT-EXIST", {"water_level_cm": 10.0, "rainfall_mm": 0.0})
        assert result["status"] == "unknown_station"
        assert SensorReading.objects.count() == 0

    def test_valid_reading_creates_record_and_updates_station(self):
        station = SensorStation.objects.create(
            name="Test Station", serial_number="ESP32-TEST-001",
            location=Point(-0.21, 5.57, srid=4326), status=StationStatus.OFFLINE,
        )
        result = ingest_sensor_reading(station.serial_number, {
            "water_level_cm": 35.0, "rainfall_mm": 2.0, "battery_voltage": 3.9,
        })
        assert result["status"] == "ok"
        station.refresh_from_db()
        assert station.status == StationStatus.ONLINE
        assert station.last_reading_at is not None
        assert SensorReading.objects.filter(station=station).exists()

    def test_battery_voltage_converted_to_percentage(self):
        station = SensorStation.objects.create(
            name="Battery Test", serial_number="ESP32-BATT-001",
            location=Point(-0.21, 5.57, srid=4326),
        )
        ingest_sensor_reading(station.serial_number, {
            "water_level_cm": 10.0, "rainfall_mm": 0.0, "battery_voltage": 4.2,  # full charge
        })
        station.refresh_from_db()
        assert station.battery_level == pytest.approx(100.0, abs=1.0)

    def test_rejected_payload_does_not_create_reading(self):
        station = SensorStation.objects.create(
            name="Reject Test", serial_number="ESP32-REJ-001",
            location=Point(-0.21, 5.57, srid=4326),
        )
        result = ingest_sensor_reading(station.serial_number, {
            "water_level_cm": -100.0, "rainfall_mm": 0.0,
        })
        assert result["status"] == "rejected"
        assert SensorReading.objects.filter(station=station).count() == 0
