"""
Tests for the sensors app: station staleness logic, status transitions,
and the readings API.

Run via the Docker Compose stack so a real PostGIS database is available:
    docker compose exec web pytest tests/test_sensors.py -v
"""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.sensors.models import SensorReading, SensorStation, StationStatus

pytestmark = pytest.mark.django_db


def make_station(**overrides) -> SensorStation:
    defaults = dict(
        name="Agbogbloshie Gauge 1",
        location=Point(-0.2107, 5.5680, srid=4326),
        community="Agbogbloshie",
        serial_number="ESP32-001",
    )
    defaults.update(overrides)
    return SensorStation.objects.create(**defaults)


class TestSensorStation:
    def test_is_stale_with_no_readings(self):
        station = make_station()
        assert station.is_stale is True

    def test_is_stale_recent_reading(self):
        station = make_station(last_reading_at=timezone.now())
        assert station.is_stale is False

    def test_is_stale_old_reading(self, settings):
        settings.SENSOR_OFFLINE_THRESHOLD_MINUTES = 30
        station = make_station(last_reading_at=timezone.now() - timedelta(minutes=45))
        assert station.is_stale is True

    def test_refresh_status_marks_offline_when_stale(self):
        station = make_station(
            status=StationStatus.ONLINE,
            last_reading_at=timezone.now() - timedelta(hours=2),
        )
        new_status = station.refresh_status()
        assert new_status == StationStatus.OFFLINE
        station.refresh_from_db()
        assert station.status == StationStatus.OFFLINE

    def test_refresh_status_does_not_override_maintenance(self):
        station = make_station(
            status=StationStatus.MAINTENANCE,
            last_reading_at=timezone.now() - timedelta(hours=5),
        )
        assert station.refresh_status() == StationStatus.MAINTENANCE

    def test_latest_reading_returns_most_recent(self):
        station = make_station()
        old = SensorReading.objects.create(
            station=station, water_level_cm=10, rainfall_mm=0,
            timestamp=timezone.now() - timedelta(hours=1),
        )
        new = SensorReading.objects.create(
            station=station, water_level_cm=15, rainfall_mm=2,
            timestamp=timezone.now(),
        )
        assert station.latest_reading() == new
        assert station.latest_reading() != old

    def test_unique_serial_number_enforced(self):
        make_station(serial_number="ESP32-DUP")
        with pytest.raises(Exception):
            make_station(name="Other station", serial_number="ESP32-DUP")


class TestSensorStationAPI:
    def test_list_stations_returns_geojson(self):
        make_station()
        client = APIClient()
        response = client.get("/api/sensors/")
        assert response.status_code == 200
        # GeoFeatureModelSerializer wraps results in a FeatureCollection
        body = response.json()
        results = body.get("features", body.get("results", body))
        assert results is not None

    def test_create_station_requires_admin(self):
        client = APIClient()
        response = client.post("/api/sensors/", {
            "name": "New Station", "serial_number": "ESP32-099",
            "longitude": -0.20, "latitude": 5.60,
        })
        assert response.status_code in (401, 403)

    def test_readings_endpoint_filters_by_hours(self):
        station = make_station()
        SensorReading.objects.create(
            station=station, water_level_cm=5, rainfall_mm=0,
            timestamp=timezone.now() - timedelta(hours=48),
        )
        recent = SensorReading.objects.create(
            station=station, water_level_cm=20, rainfall_mm=5,
            timestamp=timezone.now(),
        )
        client = APIClient()
        response = client.get(f"/api/sensors/{station.id}/readings/?hours=24")
        assert response.status_code == 200
        ids = [r["id"] for r in response.json().get("results", response.json())]
        assert recent.id in ids
