"""
Gunicorn production configuration for FloodWatch Ghana.

Run with: gunicorn -c deployment/gunicorn/gunicorn.conf.py floodwatch.wsgi:application
"""
import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# (2 x CPU cores) + 1 is the standard Gunicorn worker-count heuristic --
# enough to keep CPU busy under load without over-subscribing memory on a
# small instance. Override via GUNICORN_WORKERS for a known deployment size.
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
threads = int(os.environ.get("GUNICORN_THREADS", 2))

# Satellite-triggering admin endpoints queue a Celery task and return
# immediately, but some DRF list endpoints with heavy joins (FloodMap with
# geometry) can be slow under load -- 60s is generous without masking a
# genuinely hung worker.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 60))
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to bound any slow memory growth from
# long-lived rasterio/GDAL handles opened during satellite processing
# requests -- jitter avoids all workers restarting simultaneously.
max_requests = 1000
max_requests_jitter = 100

accesslog = "-"  # stdout, captured by Docker/systemd journal
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

preload_app = True
