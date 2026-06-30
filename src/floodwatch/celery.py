"""
Celery application instance for FloodWatch Ghana.

Placed inside the ``floodwatch`` package (next to settings/urls/wsgi) rather
than the top-level ``celery/`` directory so ``celery -A floodwatch worker``
resolves it automatically via ``floodwatch/__init__.py``. The top-level
``celery/tasks/`` directory holds the actual task implementations grouped
by domain (satellite, alerts, data processing) for readability; this module
is just the app + autodiscovery wiring.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.development")

app = Celery("floodwatch")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks.py in every app under apps.*, plus the standalone
# celery/tasks/ modules for cross-cutting jobs that don't belong to one app.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
