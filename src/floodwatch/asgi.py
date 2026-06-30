"""
ASGI config for the FloodWatch Ghana project.

Exposes the ASGI callable as ``application``. Routes HTTP through Django's
normal view stack and WebSocket connections through Channels to the
consumers defined in ``apps.sensors.consumers`` (live sensor readings,
flood alerts, and dashboard status updates).

Run with Daphne in production:
    daphne -b 0.0.0.0 -p 8001 floodwatch.asgi:application
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.production")

# get_asgi_application() must be called before importing anything that
# touches Django models (e.g. routing -> consumers -> models), otherwise
# Django raises AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from apps.sensors.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
