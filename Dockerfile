# FloodWatch Ghana — production/development container image
#
# Base image ships GDAL/GEOS/PROJ system libraries pre-installed, which
# GeoDjango (django.contrib.gis) requires at import time — installing these
# from scratch on slim/alpine images is fragile, so we start from an image
# that already has them correctly built and linked.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.8.4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip python3-dev python3-venv \
        libpq-dev gcc build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY deployment/ ./deployment/

WORKDIR /app/src

RUN mkdir -p /app/src/media /app/src/staticfiles /app/src/logs

EXPOSE 8000 8001

# Absolute path to the gunicorn config -- WORKDIR is /app/src (so that
# `python manage.py ...` and Django's own relative paths resolve
# correctly), but that means a relative "deployment/gunicorn/..." path
# here would resolve to the nonexistent /app/src/deployment/ instead of
# the actual /app/deployment/ copied above.
CMD ["gunicorn", "-c", "/app/deployment/gunicorn/gunicorn.conf.py", "floodwatch.wsgi:application"]
