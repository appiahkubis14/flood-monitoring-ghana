"""
Celery tasks for the sensors app: MQTT ingestion, threshold checking,
station heartbeats, and data retention.

``ingest_sensor_reading`` is the landing point for every MQTT message (see
``apps.sensors.mqtt_client.SensorMQTTBridge._dispatch_reading``) -- it is
deliberately the *only* place that writes a SensorReading row, so
validation (range checks, rate-of-change checks) is enforced once instead
of being re-implemented anywhere else a reading might be created.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger("apps.sensors")

# Physically implausible values are rejected outright rather than stored --
# a stuck/faulty ESP32 sending water_level_cm=99999 must not corrupt the
# dashboard's chart scale or trigger a false RED alert.
MAX_PLAUSIBLE_WATER_LEVEL_CM = 500.0
MAX_PLAUSIBLE_RAINFALL_MM = 300.0  # per reading interval, not per hour
MIN_PLAUSIBLE_TEMPERATURE_C = -10.0
MAX_PLAUSIBLE_TEMPERATURE_C = 60.0


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def ingest_sensor_reading(self, serial_number: str, payload: dict[str, Any]) -> dict:
    """Validate and persist one MQTT reading, then broadcast it live and
    kick off an immediate threshold check for *this station only* (the
    periodic ``check_sensor_thresholds`` task still runs as a safety net
    for stations that report less frequently or missed this dispatch).
    """
    from apps.sensors.models import SensorReading, SensorStation, StationStatus

    try:
        station = SensorStation.objects.get(serial_number=serial_number)
    except SensorStation.DoesNotExist:
        logger.warning("Reading from unknown station serial_number=%r — ignoring", serial_number)
        return {"status": "unknown_station"}

    validation = _validate_reading_payload(payload)
    if not validation["valid"]:
        logger.warning(
            "Rejected reading from %s: %s (payload=%r)", serial_number, validation["reason"], payload
        )
        return {"status": "rejected", "reason": validation["reason"]}

    ts = payload.get("timestamp")
    timestamp = parse_datetime(ts) if ts else None
    if timestamp is None:
        timestamp = timezone.now()

    reading = SensorReading.objects.create(
        station=station,
        water_level_cm=payload["water_level_cm"],
        rainfall_mm=payload["rainfall_mm"],
        temperature_c=payload.get("temperature_c"),
        battery_voltage=payload.get("battery_voltage"),
        signal_strength=payload.get("signal_strength"),
        timestamp=timestamp,
        is_verified=True,
    )

    update_fields = ["last_reading_at", "status"]
    station.last_reading_at = timestamp
    station.status = StationStatus.ONLINE
    if payload.get("battery_voltage") is not None:
        # Convert voltage to an approximate percentage for the dashboard
        # battery indicator (LiPo 3.0V=empty .. 4.2V=full, clamped to [0,100]).
        voltage = payload["battery_voltage"]
        pct = max(0.0, min(100.0, (voltage - 3.0) / (4.2 - 3.0) * 100.0))
        station.battery_level = round(pct, 1)
        update_fields.append("battery_level")
    station.save(update_fields=update_fields)

    _broadcast_reading(station, reading)
    check_station_threshold.delay(station.id)

    return {"status": "ok", "reading_id": reading.id}


def _validate_reading_payload(payload: dict[str, Any]) -> dict:
    """Range + presence validation for an incoming reading payload.

    Returns ``{"valid": bool, "reason": str | None}`` rather than raising,
    so the caller can log-and-skip a single bad reading without an
    exception traceback for what is, operationally, routine sensor noise.
    """
    if "water_level_cm" not in payload or "rainfall_mm" not in payload:
        return {"valid": False, "reason": "missing required fields (water_level_cm, rainfall_mm)"}

    try:
        water_level = float(payload["water_level_cm"])
        rainfall = float(payload["rainfall_mm"])
    except (TypeError, ValueError):
        return {"valid": False, "reason": "water_level_cm/rainfall_mm not numeric"}

    if water_level < 0 or water_level > MAX_PLAUSIBLE_WATER_LEVEL_CM:
        return {"valid": False, "reason": f"water_level_cm {water_level} out of plausible range"}
    if rainfall < 0 or rainfall > MAX_PLAUSIBLE_RAINFALL_MM:
        return {"valid": False, "reason": f"rainfall_mm {rainfall} out of plausible range"}

    temp = payload.get("temperature_c")
    if temp is not None:
        try:
            temp = float(temp)
        except (TypeError, ValueError):
            return {"valid": False, "reason": "temperature_c not numeric"}
        if temp < MIN_PLAUSIBLE_TEMPERATURE_C or temp > MAX_PLAUSIBLE_TEMPERATURE_C:
            return {"valid": False, "reason": f"temperature_c {temp} out of plausible range"}

    return {"valid": True, "reason": None}


def _broadcast_reading(station, reading) -> None:
    """Push the new reading to all connected dashboard clients over the
    ``sensors_live`` WebSocket group. Swallows channel-layer errors -- a
    Redis blip must not fail the ingestion task, since the reading is
    already safely persisted by this point.
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            "sensors_live",
            {
                "type": "sensor.reading",
                "payload": {
                    "station_id": station.id,
                    "station_name": station.name,
                    "serial_number": station.serial_number,
                    "water_level_cm": reading.water_level_cm,
                    "rainfall_mm": reading.rainfall_mm,
                    "temperature_c": reading.temperature_c,
                    "battery_level": station.battery_level,
                    "timestamp": reading.timestamp.isoformat(),
                },
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to broadcast sensor reading over WebSocket")


@shared_task
def update_station_heartbeat(serial_number: str, payload: dict[str, Any]) -> dict:
    """Handle a lightweight status/heartbeat message (no full reading) --
    used by ESP32 firmware to report liveness + battery between regular
    reading intervals, e.g. every 60s vs a 5-minute reading interval.
    """
    from apps.sensors.models import SensorStation, StationStatus

    try:
        station = SensorStation.objects.get(serial_number=serial_number)
    except SensorStation.DoesNotExist:
        return {"status": "unknown_station"}

    update_fields = ["status"]
    station.status = StationStatus.ONLINE
    if "ip_address" in payload:
        station.ip_address = payload["ip_address"]
        update_fields.append("ip_address")
    if "battery_voltage" in payload:
        voltage = payload["battery_voltage"]
        pct = max(0.0, min(100.0, (voltage - 3.0) / (4.2 - 3.0) * 100.0))
        station.battery_level = round(pct, 1)
        update_fields.append("battery_level")
    station.save(update_fields=update_fields)
    return {"status": "ok"}


@shared_task
def check_station_threshold(station_id: int) -> dict | None:
    """Immediate threshold check for one station, triggered right after a
    new reading lands (in addition to the periodic sweep below).
    """
    from apps.sensors.models import SensorStation

    try:
        station = SensorStation.objects.select_related("flood_zone").get(pk=station_id)
    except SensorStation.DoesNotExist:
        return None
    return _evaluate_station(station)


@shared_task
def check_sensor_thresholds() -> dict:
    """Periodic sweep (every 5 min by default, see CELERY_BEAT_SCHEDULE):
    evaluate every online station's latest reading against its zone's
    thresholds. Acts as the safety net for stations whose
    per-reading immediate check (``check_station_threshold``) was missed
    (e.g. the worker was restarted between ingestion and the immediate
    check task running).
    """
    from apps.sensors.models import SensorStation, StationStatus

    stations = SensorStation.objects.filter(status=StationStatus.ONLINE).select_related("flood_zone")
    triggered_count = 0
    for station in stations:
        station.refresh_status()  # demote to OFFLINE if it's gone stale
        if station.status != StationStatus.ONLINE:
            continue
        result = _evaluate_station(station)
        if result and result.get("triggered"):
            triggered_count += 1

    return {"checked": stations.count(), "triggered": triggered_count}


def _evaluate_station(station) -> dict | None:
    """Shared logic between the immediate and periodic threshold checks:
    evaluate the latest reading, and if it's at or above YELLOW, find-or-
    create the corresponding FloodEvent and fan out alerts.
    """
    from apps.alerts.models import FloodEvent
    from apps.alerts.rules import AlertRules, SeverityLevel, severity_rank
    from apps.alerts.tasks import create_and_send_alerts

    reading = station.latest_reading()
    if reading is None or station.flood_zone is None:
        return None

    rules = AlertRules()
    water_result = rules.evaluate_water_level(reading.water_level_cm, station.flood_zone)
    rain_result = rules.evaluate_rainfall(reading.rainfall_mm, station.flood_zone)
    combined = water_result if severity_rank(water_result.severity) >= severity_rank(rain_result.severity) else rain_result

    if combined.severity == SeverityLevel.GREEN:
        return {"triggered": False}

    # Find an existing *active* event for this zone, or open a new one.
    event = FloodEvent.objects.filter(flood_zone=station.flood_zone, ended_at__isnull=True).first()
    if event is None:
        event = FloodEvent.objects.create(
            flood_zone=station.flood_zone,
            severity=combined.severity,
            triggered_by="sensor",
            started_at=timezone.now(),
            peak_water_level_cm=reading.water_level_cm,
        )
        create_and_send_alerts.delay(event.id)
        return {"triggered": True, "event_id": event.id, "severity": combined.severity, "new_event": True}

    # Existing event: escalate severity / peak water level, but only
    # re-dispatch alerts if severity actually increased -- otherwise every
    # 5-minute sweep would re-spam recipients for an already-known event.
    escalated = severity_rank(combined.severity) > severity_rank(event.severity)
    update_fields = []
    if reading.water_level_cm and (event.peak_water_level_cm is None or reading.water_level_cm > event.peak_water_level_cm):
        event.peak_water_level_cm = reading.water_level_cm
        update_fields.append("peak_water_level_cm")
    if escalated:
        event.severity = combined.severity
        update_fields.append("severity")
    if update_fields:
        event.save(update_fields=update_fields)
    if escalated:
        create_and_send_alerts.delay(event.id)

    return {"triggered": True, "event_id": event.id, "severity": combined.severity, "escalated": escalated}


@shared_task
def archive_old_readings(retention_days: int = 90) -> dict:
    """Delete SensorReading rows older than ``retention_days``.

    Runs daily via Celery beat. A hard delete (not a soft-archive flag) is
    appropriate here because raw high-frequency telemetry has no long-term
    analytical value once a station's hourly/daily aggregates would have
    already been captured in any historical reporting -- keeping every
    5-minute reading forever just grows the table without benefit.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)
    from apps.sensors.models import SensorReading

    deleted, _ = SensorReading.objects.filter(timestamp__lt=cutoff).delete()
    logger.info("archive_old_readings: deleted %d readings older than %s", deleted, cutoff)
    return {"deleted": deleted}
