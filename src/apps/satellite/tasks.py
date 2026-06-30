"""
Celery tasks for the satellite app -- thin wrappers around
:class:`apps.satellite.processors.SatelliteProcessor` so the beat schedule
(``settings.CELERY_BEAT_SCHEDULE``) and the manual-trigger admin endpoint
(``POST /api/admin/satellite/run``) both call the same well-tested
pipeline rather than duplicating orchestration logic in task bodies.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("apps.satellite")


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def sync_satellite_scenes(self) -> dict:
    """Discover new Sentinel-1/2 scenes for the Accra study area (no
    download/processing) -- scheduled every 6h via Celery beat.
    """
    from apps.satellite.processors import SatelliteProcessor

    try:
        processor = SatelliteProcessor()
        return processor.sync_scenes()
    except Exception as exc:
        logger.exception("sync_satellite_scenes failed")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def process_satellite_data(self) -> dict:
    """Full monitoring cycle: discover + download + preprocess + detect.
    Scheduled daily via Celery beat; also the task fired by the admin
    "run satellite monitoring now" endpoint.
    """
    from apps.satellite.processors import SatelliteProcessor

    try:
        processor = SatelliteProcessor()
        return processor.run_monitoring_cycle()
    except Exception as exc:
        logger.exception("process_satellite_data failed")
        raise self.retry(exc=exc)


@shared_task
def update_flood_risk_zones() -> dict:
    """Recompute each FloodZone's current_risk_level from active
    FloodEvents -- scheduled hourly via Celery beat, much cheaper than a
    full satellite cycle so it can run far more frequently.
    """
    from apps.satellite.processors import SatelliteProcessor

    processor = SatelliteProcessor()
    return processor.update_flood_risk_zones()
