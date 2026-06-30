"""
Cross-cutting Celery task modules that don't belong to a single Django app.

NOTE: this package is deliberately named ``celery_tasks``, not ``celery`` --
a top-level ``celery/`` directory shadows the real ``celery`` PyPI package
for any process that has the project root on ``sys.path`` (which Django's
manage.py and most deployment commands do), causing
``ImportError: cannot import name 'Celery' from 'celery'``. The actual
Celery application instance lives in ``src/floodwatch/celery.py`` instead;
this package only holds task implementations that are imported by it via
``app.autodiscover_tasks()``.
"""
