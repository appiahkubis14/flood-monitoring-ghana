"""
Production settings — hardened security, real email, S3-ready media storage.

Every secret-bearing value here is read from the environment; nothing is
hard-coded. Raises loudly at import time if a required production secret is
missing, rather than silently falling back to an insecure default.
"""
from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_list, BASE_DIR

DEBUG = False

# ── Fail loudly if critical secrets are missing in production ────────────────
_REQUIRED_PROD_VARS = ["DJANGO_SECRET_KEY", "DB_PASSWORD"]
_missing = [v for v in _REQUIRED_PROD_VARS if not env(v)]
if _missing:
    raise RuntimeError(
        f"Missing required production environment variables: {', '.join(_missing)}. "
        "Set them in .env or your deployment secrets manager before starting."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")

# ── HTTPS enforcement ──────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "")

# ── Static files: compressed manifest storage ────────────────────────────────
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

# ── Optional S3 media storage ─────────────────────────────────────────────────
if env_bool("USE_S3_MEDIA", False):
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", "eu-west-1")
    AWS_DEFAULT_ACL = None
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

# ── Email (admin alerts) ──────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "alerts@floodwatch.gh")
ADMINS = [tuple(pair.split(":")) for pair in env_list("DJANGO_ADMINS", "")]

# ── Database connection pooling ───────────────────────────────────────────────
DATABASES["default"]["CONN_MAX_AGE"] = int(env("DB_CONN_MAX_AGE", "300"))
DATABASES["default"]["OPTIONS"]["sslmode"] = env("DB_SSL_MODE", "require")

# ── Stricter logging: file handler in addition to console ────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING["handlers"]["file"] = {
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(LOG_DIR / "floodwatch.log"),
    "maxBytes": 1024 * 1024 * 20,  # 20 MB
    "backupCount": 10,
    "formatter": "verbose",
}
for logger_cfg in LOGGING["loggers"].values():
    logger_cfg["handlers"] = ["console", "file"]
LOGGING["root"]["handlers"] = ["console", "file"]
