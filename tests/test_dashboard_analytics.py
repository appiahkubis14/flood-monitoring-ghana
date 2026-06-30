"""
Tests for the dashboard analytics endpoints that back the satellite
flood-maps page and the historical-trends page.

These are pure aggregation endpoints over the satellite/alerts models, so the
tests seed a few rows and assert the rolled-up numbers and shapes are correct
-- the same numbers the dashboard charts render.
"""
from datetime import date

import pytest
from django.contrib.gis.geos import Polygon
from django.utils import timezone


@pytest.fixture
def zone(db):
    from apps.satellite.models import FloodZone
    return FloodZone.objects.create(
        name="Odaw Basin",
        geometry=Polygon(((-0.22, 5.55), (-0.20, 5.55), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.55)), srid=4326),
        rainfall_threshold_mm=30,
        population_estimate=85000,
        current_risk_level="green",
    )


@pytest.fixture
def flood_map(db, zone):
    from apps.satellite.models import FloodMap, SatelliteScene, SatelliteSource, SceneStatus
    scene = SatelliteScene.objects.create(
        scene_id="S2_TEST_001", source=SatelliteSource.SENTINEL2,
        provider="planetary_computer", acquisition_date=timezone.now(),
        status=SceneStatus.PROCESSED,
    )
    return FloodMap.objects.create(
        source_scene=scene, flood_zone=zone, flooded_area_ha=42.5,
        confidence=0.78, confirmed_by_sensors=True, detection_method="mndwi_threshold",
    )


@pytest.mark.django_db
def test_satellite_overview(client, flood_map):
    resp = client.get("/api/dashboard/stats/satellite/overview/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["total_flood_maps"] == 1
    assert body["totals"]["total_flooded_area_ha"] == 42.5
    assert body["totals"]["sensor_confirmed"] == 1
    assert body["totals"]["confirmed_pct"] == 100.0
    assert body["latest_map"]["zone_name"] == "Odaw Basin"


@pytest.mark.django_db
def test_satellite_flood_area_trend(client, flood_map):
    resp = client.get("/api/dashboard/stats/satellite/flood-area-trend/?days=90")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["days"]) == 1
    assert body["flooded_area_ha"][0] == 42.5
    assert body["map_counts"][0] == 1


@pytest.mark.django_db
def test_satellite_area_by_zone(client, flood_map):
    resp = client.get("/api/dashboard/stats/satellite/area-by-zone/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["zones"] == ["Odaw Basin"]
    assert body["flooded_area_ha"] == [42.5]


@pytest.mark.django_db
def test_satellite_overview_empty(client):
    """No flood maps yet -> endpoint must still return a valid zeroed payload,
    not error (a fresh deployment has no data)."""
    resp = client.get("/api/dashboard/stats/satellite/overview/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["total_flood_maps"] == 0
    assert body["latest_map"] is None


@pytest.mark.django_db
def test_historical_flood_trend(client, zone):
    from apps.alerts.models import HistoricalFloodRecord
    HistoricalFloodRecord.objects.create(
        flood_zone=zone, event_date=date(2023, 6, 3), severity="red",
        rainfall_mm=120, affected_area_ha=300, casualties=14, displaced_persons=4000, source="NADMO 2023",
    )
    HistoricalFloodRecord.objects.create(
        flood_zone=zone, event_date=date(2022, 6, 15), severity="orange",
        rainfall_mm=85, affected_area_ha=150, casualties=3, displaced_persons=1200, source="GhanaWeb",
    )
    resp = client.get("/api/dashboard/stats/historical-flood-trend/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["total_events"] == 2
    assert body["totals"]["total_casualties"] == 17
    assert body["totals"]["total_displaced"] == 5200
    assert body["yearly"]["years"] == [2022, 2023]
    assert body["yearly"]["casualties"] == [3, 14]
    # points are ordered by event_date ascending
    assert body["points"][0]["date"] == "2022-06-15"


@pytest.mark.django_db
def test_satellite_flood_maps_page_renders(client, flood_map):
    resp = client.get("/dashboard/flood-maps/")
    assert resp.status_code == 200
    assert b"Satellite-Derived Flood Maps" in resp.content
    assert b"sat-chart-trend" in resp.content


@pytest.mark.django_db
def test_historical_trends_page_renders(client, zone):
    resp = client.get("/dashboard/flood-maps/timeseries/")
    assert resp.status_code == 200
    assert b"Historical Flood Trend Analysis" in resp.content
    assert b"ht-chart-impact" in resp.content
