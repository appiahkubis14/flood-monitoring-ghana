"""
Management command: run the MQTT-to-Celery bridge as a long-lived process.

Usage:
    python manage.py run_mqtt_bridge

Run this in its own container/process (see docker-compose.yml's planned
``mqtt_bridge`` service) -- it blocks forever on ``loop_forever()`` and must
never share a process with Gunicorn, Daphne, or a Celery worker.
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.sensors.mqtt_client import SensorMQTTBridge

logger = logging.getLogger("apps.sensors")


class Command(BaseCommand):
    help = "Run the MQTT bridge that forwards ESP32 sensor readings into Celery for ingestion."

    def handle(self, *args, **options) -> None:
        bridge = SensorMQTTBridge()
        self.stdout.write(self.style.SUCCESS("Starting MQTT bridge..."))
        try:
            bridge.connect()
            bridge.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write("Shutting down MQTT bridge (KeyboardInterrupt)...")
        finally:
            bridge.disconnect()
