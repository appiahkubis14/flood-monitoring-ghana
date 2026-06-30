"""
Base Django settings for the FloodWatch Ghana project.

Shared by development and production. Environment-specific overrides live in
``development.py`` and ``production.py``, which both start with
``from .base import *``.

Secrets and environment-dependent values are read from a ``.env`` file via
python-dotenv — never hard-code credentials here.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────────
# BASE_DIR -> floodwatch_ghana/src/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# PROJECT_ROOT -> floodwatch_ghana/ (one level above src/), where .env lives
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")


def env(key: str, default: str | None = None) -> str | None:
    """Read an environment variable, falling back to *default*."""
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(key: str, default: str = "") -> list[str]:
    val = os.environ.get(key, default)
    return [item.strip() for item in val.split(",") if item.strip()]


# ── Core ───────────────────────────────────────────────────────────────────────
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Region constant used across the satellite + dashboard apps.
# (minlon, minlat, maxlon, maxlat) — Greater Accra, Ghana, WGS84.
# Covers the Odaw River basin, Korle Lagoon, and surrounding low-lying coast.
ACCRA_BBOX = (
    float(env("ACCRA_BBOX_MINLON", "-0.30")),
    float(env("ACCRA_BBOX_MINLAT", "5.50")),
    float(env("ACCRA_BBOX_MAXLON", "-0.05")),
    float(env("ACCRA_BBOX_MAXLAT", "5.70")),
)

# ── Applications ───────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",  # PostGIS / GeoDjango
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_gis",
    "corsheaders",
    "channels",
    "django_celery_results",
    "django_celery_beat",
    "django_extensions",
    "django_filters",
]

LOCAL_APPS = [
    "apps.core",
    "apps.users",
    "apps.sensors",
    "apps.satellite",
    "apps.alerts",
    "apps.dashboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "floodwatch.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context_processors.flood_status",
            ],
        },
    },
]

WSGI_APPLICATION = "floodwatch.wsgi.application"
ASGI_APPLICATION = "floodwatch.asgi.application"

# ── Database (PostgreSQL + PostGIS) ───────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env("DB_NAME", "floodwatch"),
        "USER": env("DB_USER", "floodwatch"),
        "PASSWORD": env("DB_PASSWORD", "floodwatch"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# ── Auth ───────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# ── I18N ───────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
# Africa/Accra is GMT, no DST — chosen explicitly rather than left as UTC
# so all sensor/alert timestamps shown to users are already local time.
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

# ── Static & media ─────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Django REST Framework ─────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DATETIME_FORMAT": "iso-8601",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=2),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "FloodWatch Ghana API",
    "DESCRIPTION": "Hybrid IoT + satellite flood monitoring system for Accra, Ghana.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ── CORS ───────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True

# ── Channels (WebSockets) ──────────────────────────────────────────────────────
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(env("REDIS_HOST", "localhost"), int(env("REDIS_PORT", "6379")))],
        },
    },
}

# ── Celery ─────────────────────────────────────────────────────────────────────
REDIS_URL = env("REDIS_URL", f"redis://{env('REDIS_HOST', 'localhost')}:{env('REDIS_PORT', '6379')}/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 min hard limit (satellite jobs can be slow)

CELERY_BEAT_SCHEDULE = {
    "sync-satellite-scenes-every-6h": {
        "task": "apps.satellite.tasks.sync_satellite_scenes",
        "schedule": timedelta(hours=6),
    },
    "process-satellite-data-daily": {
        "task": "apps.satellite.tasks.process_satellite_data",
        "schedule": timedelta(hours=24),
    },
    "check-sensor-thresholds-every-5min": {
        "task": "apps.sensors.tasks.check_sensor_thresholds",
        "schedule": timedelta(minutes=5),
    },
    "update-flood-risk-zones-every-hour": {
        "task": "apps.satellite.tasks.update_flood_risk_zones",
        "schedule": timedelta(hours=1),
    },
    "archive-old-readings-daily": {
        "task": "apps.sensors.tasks.archive_old_readings",
        "schedule": timedelta(hours=24),
    },
    "generate-daily-report": {
        "task": "apps.alerts.tasks.generate_daily_report",
        "schedule": timedelta(hours=24),
    },
}

# ── Caching ────────────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

# ── Twilio (WhatsApp / SMS) ────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = env("TWILIO_WHATSAPP_FROM", "")  # e.g. "whatsapp:+14155238886"
TWILIO_SMS_FROM = env("TWILIO_SMS_FROM", "")

# ── MQTT ───────────────────────────────────────────────────────────────────────
MQTT_BROKER_HOST = env("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(env("MQTT_BROKER_PORT", "1883"))
MQTT_USERNAME = env("MQTT_USERNAME", "")
MQTT_PASSWORD = env("MQTT_PASSWORD", "")
MQTT_TOPIC_PREFIX = env("MQTT_TOPIC_PREFIX", "floodwatch/sensors")
# Sensors that haven't reported within this window are flagged OFFLINE.
SENSOR_OFFLINE_THRESHOLD_MINUTES = int(env("SENSOR_OFFLINE_THRESHOLD_MINUTES", "30"))

# ── PyGeoVision satellite monitoring ──────────────────────────────────────────
PYGEOVISION_DATA_DIR = Path(env("PYGEOVISION_DATA_DIR", str(BASE_DIR / "media" / "satellite")))
PYGEOVISION_PROVIDERS = env_list("PYGEOVISION_PROVIDERS", "planetary_computer")
PYGEOVISION_CLOUD_COVER_MAX = float(env("PYGEOVISION_CLOUD_COVER_MAX", "20"))
PYGEOVISION_S2_BANDS = env_list("PYGEOVISION_S2_BANDS", "B02,B03,B04,B08,B11,B12")
PYGEOVISION_SCAN_DAYS_BACK = int(env("PYGEOVISION_SCAN_DAYS_BACK", "7"))

# ── Alert cooldown ─────────────────────────────────────────────────────────────
# Minimum minutes between two alerts of the same type+zone, to avoid alert
# fatigue when a sensor oscillates near a threshold.
ALERT_COOLDOWN_MINUTES = int(env("ALERT_COOLDOWN_MINUTES", "30"))

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps.satellite": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps.sensors": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps.alerts": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# Optional explicit GDAL/GEOS library paths — needed in sandboxed/CI
# environments where GDAL is not registered via standard system paths.
# Leave unset (commented) on normal deployments with apt-installed GDAL.
_gdal_path = env("GDAL_LIBRARY_PATH")
if _gdal_path:
    GDAL_LIBRARY_PATH = _gdal_path
_geos_path = env("GEOS_LIBRARY_PATH")
if _geos_path:
    GEOS_LIBRARY_PATH = _geos_path
