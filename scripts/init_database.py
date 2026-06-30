#!/usr/bin/env python3
"""
Initial data load for FloodWatch Ghana.

Seeds the predefined flood risk zones along the Odaw River basin and Korle
Lagoon, plus a starter set of sensor stations and an admin alert recipient.
Idempotent -- safe to re-run; uses ``get_or_create`` throughout so it never
duplicates rows.

Usage (from the project root, inside the Docker stack):
    docker compose exec web python scripts/init_database.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `apps.*` importable when run as a standalone script.
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.development")

import django  # noqa: E402

django.setup()

from django.contrib.gis.geos import Point, Polygon  # noqa: E402

from apps.alerts.models import AlertRecipient  # noqa: E402
from apps.satellite.models import FloodZone  # noqa: E402
from apps.sensors.models import SensorStation  # noqa: E402


# Approximate sub-catchment polygons along the Odaw River basin / Korle
# Lagoon, WGS84. These are illustrative starting boundaries -- replace with
# surveyed/official GIS boundaries before relying on them operationally.
FLOOD_ZONES = [
    {
        "name": "Odaw River Basin — Alajo",
        "geometry": Polygon((
            (-0.2250, 5.5950), (-0.2050, 5.5950),
            (-0.2050, 5.6150), (-0.2250, 5.6150), (-0.2250, 5.5950),
        ), srid=4326),
        "water_level_threshold_cm": 45.0,
        "rainfall_threshold_mm": 35.0,
        "population_estimate": 38000,
        "description": "Upper Odaw catchment, prone to flash flooding after heavy upstream rainfall.",
    },
    {
        "name": "Korle Lagoon — Agbogbloshie",
        "geometry": Polygon((
            (-0.2200, 5.5400), (-0.2000, 5.5400),
            (-0.2000, 5.5600), (-0.2200, 5.5600), (-0.2200, 5.5400),
        ), srid=4326),
        "water_level_threshold_cm": 50.0,
        "rainfall_threshold_mm": 40.0,
        "population_estimate": 52000,
        "description": "Korle Lagoon outlet; combines river discharge with tidal backflow during storms.",
    },
    {
        "name": "Odaw River Basin — Avenor / Kaneshie",
        "geometry": Polygon((
            (-0.2400, 5.5650), (-0.2200, 5.5650),
            (-0.2200, 5.5850), (-0.2400, 5.5850), (-0.2400, 5.5650),
        ), srid=4326),
        "water_level_threshold_cm": 40.0,
        "rainfall_threshold_mm": 30.0,
        "population_estimate": 29000,
        "description": "Low-lying market and residential area, historically the worst-affected zone in major Accra floods.",
    },
]

STARTER_STATIONS = [
    {
        "name": "Alajo Bridge Gauge",
        "location": Point(-0.2140, 5.6050, srid=4326),
        "community": "Alajo",
        "serial_number": "ESP32-ALJ-001",
    },
    {
        "name": "Agbogbloshie Market Gauge",
        "location": Point(-0.2107, 5.5495, srid=4326),
        "community": "Agbogbloshie",
        "serial_number": "ESP32-AGB-001",
    },
    {
        "name": "Kaneshie Roundabout Gauge",
        "location": Point(-0.2305, 5.5740, srid=4326),
        "community": "Kaneshie",
        "serial_number": "ESP32-KNS-001",
    },
]


def run() -> None:
    print("=" * 60)
    print("FloodWatch Ghana — initial data load")
    print("=" * 60)

    zones_by_name = {}
    for zdata in FLOOD_ZONES:
        zone, created = FloodZone.objects.get_or_create(
            name=zdata["name"],
            defaults={k: v for k, v in zdata.items() if k != "name"},
        )
        zones_by_name[zone.name] = zone
        print(f"  {'Created' if created else 'Exists '} FloodZone: {zone.name}")

    zone_names = list(zones_by_name.values())
    for i, sdata in enumerate(STARTER_STATIONS):
        zone = zone_names[i % len(zone_names)] if zone_names else None
        station, created = SensorStation.objects.get_or_create(
            serial_number=sdata["serial_number"],
            defaults={**{k: v for k, v in sdata.items() if k != "serial_number"}, "flood_zone": zone},
        )
        print(f"  {'Created' if created else 'Exists '} SensorStation: {station.name}")

    admin_recipient, created = AlertRecipient.objects.get_or_create(
        phone_number="+233000000000",
        defaults={"full_name": "FloodWatch Admin (placeholder)", "preferred_channel": "dashboard"},
    )
    print(f"  {'Created' if created else 'Exists '} AlertRecipient: {admin_recipient.full_name}")

    print("\nDone. Replace the placeholder admin recipient's phone number")
    print("and add real community alert subscribers via the admin panel.")


if __name__ == "__main__":
    run()
