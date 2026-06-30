"""
Tests for the satellite app models: FloodZone, SatelliteScene, FloodMap.

The actual PyGeoVision processing pipeline (apps.satellite.processors) is
covered separately in Phase 3 once that module is built; this file tests
the data-layer models that the pipeline writes into.

Run via Docker Compose: docker compose exec web pytest tests/test_satellite.py -v
"""
import pytest
from django.contrib.gis.geos import Polygon
from django.utils import timezone

from apps.satellite.models import (
    FloodMap,
    FloodZone,
    SatelliteScene,
    SatelliteSource,
    SceneStatus,
)

pytestmark = pytest.mark.django_db

ODAW_BASIN_POLY = Polygon((
    (-0.22, 5.56), (-0.20, 5.56), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.56),
), srid=4326)


def make_flood_zone(**overrides) -> FloodZone:
    defaults = dict(name="Odaw River Basin — Alajo", geometry=ODAW_BASIN_POLY)
    defaults.update(overrides)
    return FloodZone.objects.create(**defaults)


class TestFloodZone:
    def test_default_risk_level_is_green(self):
        zone = make_flood_zone()
        assert zone.current_risk_level == "green"

    def test_str_includes_risk_level(self):
        zone = make_flood_zone(current_risk_level="red")
        assert "Emergency" in str(zone)


class TestSatelliteScene:
    def test_scene_id_unique(self):
        SatelliteScene.objects.create(
            scene_id="S2A_MSIL2A_20240101", source=SatelliteSource.SENTINEL2,
            provider="planetary_computer", acquisition_date=timezone.now(),
        )
        with pytest.raises(Exception):
            SatelliteScene.objects.create(
                scene_id="S2A_MSIL2A_20240101", source=SatelliteSource.SENTINEL2,
                provider="copernicus", acquisition_date=timezone.now(),
            )

    def test_default_status_is_discovered(self):
        scene = SatelliteScene.objects.create(
            scene_id="S1A_GRD_20240102", source=SatelliteSource.SENTINEL1,
            provider="planetary_computer", acquisition_date=timezone.now(),
        )
        assert scene.status == SceneStatus.DISCOVERED


class TestFloodMap:
    def test_flood_map_links_to_zone_and_scene(self):
        zone = make_flood_zone()
        scene = SatelliteScene.objects.create(
            scene_id="S2A_MSIL2A_20240103", source=SatelliteSource.SENTINEL2,
            provider="planetary_computer", acquisition_date=timezone.now(),
        )
        flood_map = FloodMap.objects.create(
            source_scene=scene, flood_zone=zone, flooded_area_ha=12.5, confidence=0.87,
        )
        assert flood_map.flood_zone == zone
        assert flood_map.source_scene == scene
        assert "12.5" in str(flood_map) or "ha)" in str(flood_map)

    def test_unconfirmed_by_default(self):
        flood_map = FloodMap.objects.create(flooded_area_ha=1.0)
        assert flood_map.confirmed_by_sensors is False
