"""
NOTE: task implementations live in each Django app's own tasks.py module
(apps.sensors.tasks, apps.satellite.tasks, apps.alerts.tasks), not here.

Celery's ``app.autodiscover_tasks()`` (configured in
src/floodwatch/celery.py) automatically finds a ``tasks.py`` inside every
app listed in INSTALLED_APPS -- that is the idiomatic Django+Celery
pattern, and registering the *same* task logic a second time under this
module's dotted path would create duplicate, confusingly-named task
registrations (e.g. both ``apps.satellite.tasks.process_satellite_data``
and ``celery_tasks.tasks.satellite_tasks.process_satellite_data`` existing
as separate Celery tasks for the same underlying code).

This file is kept as a deliberately empty placeholder matching the
originally specified project structure (celery/tasks/data_processing.py), rather than
silently deleted, so its absence is never mistaken for a missing feature.

See instead:
  apps.sensors.tasks    -- ingest_sensor_reading, check_sensor_thresholds, archive_old_readings
  apps.satellite.tasks  -- sync_satellite_scenes, process_satellite_data, update_flood_risk_zones
  apps.alerts.tasks     -- create_and_send_alerts, send_alert, generate_daily_report, send_community_broadcast
"""
