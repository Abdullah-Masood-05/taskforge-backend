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

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "silk.middleware.SilkyMiddleware",
] + MIDDLEWARE  # noqa: F405

INTERNAL_IPS = ["127.0.0.1", "::1"]

# Disable axes lockout in dev (optional — comment out to test brute-force)
AXES_ENABLED = False

# Looser CORS in dev
CORS_ALLOW_ALL_ORIGINS = True

# Faster password hashing in dev/tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Silk profiling
SILKY_PYTHON_PROFILER = True
