"""Development settings — local debugging, relaxed security, Debug Toolbar."""
from .base import *  # noqa: F401,F403
from .base import env_bool, MIDDLEWARE, INSTALLED_APPS

DEBUG = True

INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE

INTERNAL_IPS = ["127.0.0.1"]

# Relaxed CORS for local frontend dev servers (Vite/React on :3000, :5173, etc.)
CORS_ALLOW_ALL_ORIGINS = True

# Don't force HTTPS locally.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Convenient local Celery behaviour: run tasks eagerly only if explicitly requested
# (keep this False by default so you still exercise the real worker locally).
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
