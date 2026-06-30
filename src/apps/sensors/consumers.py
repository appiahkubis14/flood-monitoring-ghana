"""
WebSocket consumers for real-time sensor and alert broadcasting.

These are minimal working consumers for Phase 1 (they accept connections
and join the right broadcast groups) so the ASGI app is fully wired end to
end. The Celery tasks / MQTT bridge that call ``group_send`` to push actual
readings land in Phase 2.
"""
from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class SensorConsumer(AsyncJsonWebsocketConsumer):
    """Broadcasts live SensorReading events to connected dashboard clients."""

    GROUP_NAME = "sensors_live"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def sensor_reading(self, event: dict) -> None:
        """Handler for ``type: "sensor.reading"`` group_send events."""
        await self.send_json(event["payload"])


class AlertConsumer(AsyncJsonWebsocketConsumer):
    """Broadcasts new Alert / FloodEvent updates to connected dashboard clients."""

    GROUP_NAME = "alerts_live"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def alert_created(self, event: dict) -> None:
        """Handler for ``type: "alert.created"`` group_send events."""
        await self.send_json(event["payload"])
