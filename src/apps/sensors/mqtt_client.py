"""
MQTT bridge between ESP32 sensor stations and the Django/Celery backend.

Topic convention (configurable via ``MQTT_TOPIC_PREFIX``):

    floodwatch/sensors/<serial_number>/reading      -- telemetry payload
    floodwatch/sensors/<serial_number>/status        -- online/LWT heartbeat

Payload (JSON) for a reading::

    {
        "water_level_cm": 23.4,
        "rainfall_mm": 1.2,
        "temperature_c": 27.8,
        "battery_voltage": 3.7,
        "signal_strength": -62,
        "timestamp": "2026-06-30T08:15:00Z"   // optional; server time used if absent
    }

This module runs as a long-lived background process (see
``manage.py run_mqtt_bridge`` in ``apps/sensors/management/commands/``),
separate from the Django request/response cycle and separate from Celery
workers -- it needs a persistent TCP connection to the broker, which neither
of those process models is built for.

Validation, persistence, and downstream side effects (WebSocket broadcast,
threshold checks) are deliberately *not* done inline in the MQTT callback --
each incoming message is handed to a Celery task
(``apps.sensors.tasks.ingest_sensor_reading``) so a slow database write or a
threshold-check bug can never block the MQTT event loop or cause the broker
to see this client as unresponsive.

Written against paho-mqtt 2.x's explicit ``CallbackAPIVersion.VERSION2`` API
(the default changed from 1.x's implicit callback signatures, which are
deprecated and emit a DeprecationWarning on every connect under 2.x).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger("apps.sensors")


class SensorMQTTBridge:
    """Subscribes to all sensor topics and forwards parsed payloads to Celery.

    Example (run via the management command)::

        bridge = SensorMQTTBridge()
        bridge.connect()
        bridge.loop_forever()   # blocks; run this in its own process/container
    """

    def __init__(self) -> None:
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="floodwatch-django-bridge",
            protocol=mqtt.MQTTv311,
        )
        if settings.MQTT_USERNAME:
            self.client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    # ── Connection lifecycle ───────────────────────────────────────────────

    def connect(self) -> None:
        logger.info(
            "Connecting to MQTT broker %s:%s", settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT
        )
        self.client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)

    def loop_forever(self) -> None:
        """Blocking event loop -- call this from a dedicated long-running
        process (e.g. ``python manage.py run_mqtt_bridge``), never from a
        request handler or a Celery task.
        """
        self.client.loop_forever()

    def disconnect(self) -> None:
        self.client.disconnect()

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict,
                     reason_code: Any, properties: Any = None) -> None:
        if reason_code != 0:
            logger.error("MQTT connect failed: %s", reason_code)
            return
        reading_topic = f"{settings.MQTT_TOPIC_PREFIX}/+/reading"
        status_topic = f"{settings.MQTT_TOPIC_PREFIX}/+/status"
        client.subscribe(reading_topic, qos=1)
        client.subscribe(status_topic, qos=1)
        logger.info("MQTT connected; subscribed to %s and %s", reading_topic, status_topic)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any,
                        reason_code: Any, properties: Any = None) -> None:
        logger.warning("MQTT disconnected (%s); paho will auto-reconnect", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Parse the topic to extract serial_number + message type, then
        dispatch to the appropriate Celery task. Never raises -- a
        malformed message from one faulty sensor must not crash the bridge
        for every other station.
        """
        try:
            serial_number = self._serial_from_topic(msg.topic)
            if serial_number is None:
                logger.warning("Could not parse serial number from topic %r", msg.topic)
                return

            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Malformed MQTT payload on %r: %s", msg.topic, exc)
                return

            if msg.topic.endswith("/reading"):
                self._dispatch_reading(serial_number, payload)
            elif msg.topic.endswith("/status"):
                self._dispatch_status(serial_number, payload)
            else:
                logger.debug("Ignoring unrecognised topic: %s", msg.topic)

        except Exception:  # noqa: BLE001 -- intentionally broad: MQTT loop must never die
            logger.exception("Unhandled error processing MQTT message on topic %r", msg.topic)

    def _serial_from_topic(self, topic: str) -> str | None:
        # floodwatch/sensors/<serial_number>/reading -> <serial_number>
        prefix = settings.MQTT_TOPIC_PREFIX.rstrip("/")
        if not topic.startswith(prefix + "/"):
            return None
        remainder = topic[len(prefix) + 1:]
        parts = remainder.split("/")
        return parts[0] if parts else None

    def _dispatch_reading(self, serial_number: str, payload: dict) -> None:
        from apps.sensors.tasks import ingest_sensor_reading

        ingest_sensor_reading.delay(serial_number, payload)

    def _dispatch_status(self, serial_number: str, payload: dict) -> None:
        from apps.sensors.tasks import update_station_heartbeat

        update_station_heartbeat.delay(serial_number, payload)


def publish_test_reading(serial_number: str, water_level_cm: float, rainfall_mm: float) -> None:
    """Convenience helper for manual testing / demos -- publishes a single
    reading as if it came from an ESP32, without needing real hardware.

    Example::

        python manage.py shell -c "
            from apps.sensors.mqtt_client import publish_test_reading
            publish_test_reading('ESP32-ALJ-001', water_level_cm=65.0, rainfall_mm=12.0)
        "
    """
    import datetime

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)
    topic = f"{settings.MQTT_TOPIC_PREFIX}/{serial_number}/reading"
    payload = json.dumps({
        "water_level_cm": water_level_cm,
        "rainfall_mm": rainfall_mm,
        "temperature_c": 28.0,
        "battery_voltage": 3.8,
        "signal_strength": -58,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    client.publish(topic, payload, qos=1)
    client.disconnect()
