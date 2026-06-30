#!/usr/bin/env python3
"""
Bulk-register sensor stations from a CSV file -- the practical alternative
to registering each ESP32 unit one-by-one through the admin panel when
deploying a batch of stations to new communities.

CSV format (header row required):
    name,serial_number,community,longitude,latitude,flood_zone_name
    Alajo Bridge Gauge,ESP32-ALJ-002,Alajo,-0.2140,5.6050,Odaw River Basin — Alajo

``flood_zone_name`` is matched against existing FloodZone names -- if it
doesn't match any zone (typo, or zone not yet created), the station is
still registered but left unassigned to a zone rather than failing the
whole batch, since one bad row should not block deploying the other 49
stations in the same CSV.

Usage:
    docker compose exec web python scripts/deploy_sensors.py stations.csv
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.development")

import django  # noqa: E402

django.setup()

from django.contrib.gis.geos import Point  # noqa: E402

from apps.satellite.models import FloodZone  # noqa: E402
from apps.sensors.models import SensorStation  # noqa: E402


def deploy_from_csv(csv_path: str) -> None:
    created, skipped, errors = 0, 0, 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_fields = {"name", "serial_number", "longitude", "latitude"}
        missing = required_fields - set(reader.fieldnames or [])
        if missing:
            print(f"ERROR: CSV is missing required columns: {missing}")
            sys.exit(1)

        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            serial = row["serial_number"].strip()
            if not serial:
                print(f"  Row {row_num}: skipped (empty serial_number)")
                skipped += 1
                continue

            if SensorStation.objects.filter(serial_number=serial).exists():
                print(f"  Row {row_num}: {serial} already registered — skipped")
                skipped += 1
                continue

            try:
                lon = float(row["longitude"])
                lat = float(row["latitude"])
            except (KeyError, ValueError):
                print(f"  Row {row_num}: invalid longitude/latitude — skipped")
                errors += 1
                continue

            zone = None
            zone_name = row.get("flood_zone_name", "").strip()
            if zone_name:
                zone = FloodZone.objects.filter(name=zone_name).first()
                if zone is None:
                    print(f"  Row {row_num}: zone '{zone_name}' not found — registering without a zone")

            SensorStation.objects.create(
                name=row["name"].strip(),
                serial_number=serial,
                community=row.get("community", "").strip(),
                location=Point(lon, lat, srid=4326),
                flood_zone=zone,
            )
            print(f"  Row {row_num}: created {serial} ({row['name'].strip()})")
            created += 1

    print(f"\nDone: {created} created, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/deploy_sensors.py <path-to-stations.csv>")
        sys.exit(1)
    deploy_from_csv(sys.argv[1])
