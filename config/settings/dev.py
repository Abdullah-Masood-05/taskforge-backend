"""
Development settings — inherits all base settings, adds debug tools.
"""
from .base import *  # noqa: F401, F403

DEBUG = True

# Allow all hosts locally
ALLOWED_HOSTS = ["*"]

# Console email backend (base.py default) stays in dev

# Django Debug Toolbar
INSTALLED_APPS += ["debug_toolbar", "silk"]  # noqa: F405

# Insert debug tools AFTER CorsMiddleware so CORS preflight still works.
# CorsMiddleware must be first to add Access-Control-Allow-Origin headers.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "silk.middleware.SilkyMiddleware",
] + [m for m in MIDDLEWARE if m != "corsheaders.middleware.CorsMiddleware"]  # noqa: F405

INTERNAL_IPS = ["127.0.0.1", "::1"]

# Disable axes lockout in dev (optional — comment out to test brute-force)
AXES_ENABLED = False

# Looser CORS in dev
CORS_ALLOW_ALL_ORIGINS = True

# Faster password hashing in dev/tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# SQLite + ASGI: persistent connections (CONN_MAX_AGE=60 from base) cause
# "database is locked" errors under Daphne because SQLite only allows one
# writer at a time. Reset to 0 in dev so each request gets a fresh connection.
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":  # noqa: F405
    DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405

# Silk profiling
# Per-request cProfile conflicts with other active profilers (VS Code debugger,
# coverage, overlapping dev-server requests) -> "Another profiling tool is already
# active" spam on every request. Silk still records request timing + SQL without it.
SILKY_PYTHON_PROFILER = False

# ─────────────────────────────────────────────────────────────
# Celery — run tasks synchronously in dev (no worker process needed)
# ─────────────────────────────────────────────────────────────
# NOTE: Remove these two lines if you want to test with a real Celery worker.
# On Windows, start the worker with: celery -A config worker --pool=solo --loglevel=info
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True  # Propagate exceptions from tasks
