"""
Ensures the Celery app is loaded whenever Django starts, so
``@shared_task`` decorated functions across the project register correctly
without each module needing its own explicit Celery import.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
