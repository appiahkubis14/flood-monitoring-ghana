#!/usr/bin/env python3
"""
One-time setup/health-check for the PyGeoVision satellite monitoring
pipeline -- run this after deployment, before relying on the scheduled
Celery beat tasks, to confirm the pipeline can actually reach PyGeoVision
and write to its data directory.

Checks performed:
  1. pygeovision is importable and PyGeoVision() constructs without error
  2. PYGEOVISION_DATA_DIR exists and is writable
  3. A real search() call against the configured providers succeeds for
     the Accra bbox (catches misconfigured provider credentials early,
     rather than discovering it 6 hours later when the first scheduled
     sync_satellite_scenes task silently fails)
  4. At least one FloodZone exists (the detection pipeline has nothing to
     attribute flooded area to without zones -- this is usually solved by
     running scripts/init_database.py first, and this script reminds you
     if it hasn't been run)

Usage:
    docker compose exec web python scripts/setup_satellite_monitoring.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.development")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402


def check(label: str, fn) -> bool:
    try:
        fn()
        print(f"  [OK]   {label}")
        return True
    except Exception as exc:  # noqa: BLE001 -- this is a diagnostic script
        print(f"  [FAIL] {label}: {exc}")
        return False


def main() -> None:
    print("=" * 60)
    print("FloodWatch Ghana — Satellite Monitoring Setup Check")
    print("=" * 60)

    results = []

    def check_pygeovision_import():
        from pygeovision import PyGeoVision  # noqa: F401

    results.append(check("pygeovision is importable", check_pygeovision_import))

    def check_data_dir():
        data_dir = Path(settings.PYGEOVISION_DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()

    results.append(check(f"PYGEOVISION_DATA_DIR is writable ({settings.PYGEOVISION_DATA_DIR})", check_data_dir))

    def check_search():
        from pygeovision import PyGeoVision

        client = PyGeoVision()
        date_range = (
            (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d"),
        )
        results_found = client.search(
            bbox=settings.ACCRA_BBOX, date_range=date_range,
            providers=settings.PYGEOVISION_PROVIDERS, cloud_cover_max=100,
        )
        print(f"         -> found {len(results_found)} Sentinel-2 scenes in the last 14 days")

    results.append(check("Search against configured providers succeeds", check_search))

    def check_flood_zones():
        from apps.satellite.models import FloodZone

        count = FloodZone.objects.count()
        if count == 0:
            raise RuntimeError(
                "No FloodZone records exist. Run `python scripts/init_database.py` first."
            )
        print(f"         -> {count} flood zone(s) configured")

    results.append(check("At least one FloodZone is configured", check_flood_zones))

    print()
    if all(results):
        print("All checks passed. The satellite pipeline is ready to run.")
        print("Trigger it manually with: POST /api/admin/satellite/run/")
        print("Or wait for the scheduled Celery beat tasks (see settings.CELERY_BEAT_SCHEDULE).")
    else:
        print("Some checks failed -- resolve the issues above before relying on")
        print("the scheduled satellite monitoring tasks.")
        sys.exit(1)


if __name__ == "__main__":
    main()
