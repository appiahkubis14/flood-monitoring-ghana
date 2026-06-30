"""
WebSocket URL routing for the sensors app.

Consumers (in ``consumers.py``) push live sensor readings and station
status changes to connected dashboard clients. Full consumer implementation
lands in Phase 2 (IoT integration) — this file exists now so
``floodwatch.asgi`` has something stable to import.
"""
from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/sensors/$", consumers.SensorConsumer.as_asgi()),
    re_path(r"ws/alerts/$", consumers.AlertConsumer.as_asgi()),
]
