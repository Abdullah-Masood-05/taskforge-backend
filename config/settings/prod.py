"""
Production settings — deployed on Render (backend) + Netlify (frontend).

Key differences from dev:
  - Render terminates TLS at the load balancer; SECURE_SSL_REDIRECT stays False
    and SECURE_PROXY_SSL_HEADER tells Django the real protocol.
  - RENDER_EXTERNAL_HOSTNAME is auto-set by Render; we append it to ALLOWED_HOSTS.
  - S3 storage is used when AWS_STORAGE_BUCKET_NAME is set; otherwise WhiteNoise
    serves static files directly from Daphne.
  - SendGrid email is used when SENDGRID_API_KEY is set; otherwise the console
    backend is used (useful for staging environments without an email key).
  - Sentry is initialised only when SENTRY_DSN is set.
"""
import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from .base import *  # noqa: F401, F403

DEBUG = False

# ─────────────────────────────────────────────────────────────
# Allowed hosts
# ALLOWED_HOSTS env var is a comma-separated list; Render also injects
# RENDER_EXTERNAL_HOSTNAME automatically (e.g. taskforge-api.onrender.com).
# ─────────────────────────────────────────────────────────────
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
_extra_hosts = [h for h in [_render_host] if h]
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[]) + _extra_hosts  # noqa: F405

# ─────────────────────────────────────────────────────────────
# SSL — Render terminates TLS upstream; we must not redirect again
# ─────────────────────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False  # Render's load balancer already enforces HTTPS

# Security headers (safe to enable — Render forwards these to the browser)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# ─────────────────────────────────────────────────────────────
# CORS / CSRF
# ─────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[FRONTEND_URL])  # noqa: F405
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[FRONTEND_URL])  # noqa: F405

# ─────────────────────────────────────────────────────────────
# Static / media files
# Use S3 when bucket credentials are present; fall back to WhiteNoise
# ─────────────────────────────────────────────────────────────
_use_s3 = bool(os.environ.get("AWS_STORAGE_BUCKET_NAME"))

if _use_s3:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    STATICFILES_STORAGE = "storages.backends.s3boto3.S3StaticStorage"
else:
    # WhiteNoise serves compressed static files directly from the ASGI process.
    # Insert after SecurityMiddleware (index 1).
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ─────────────────────────────────────────────────────────────
# Email
# Use SendGrid when SENDGRID_API_KEY is set; fall back to console backend
# ─────────────────────────────────────────────────────────────
_sendgrid_key = os.environ.get("SENDGRID_API_KEY", "")

if _sendgrid_key:
    EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
    ANYMAIL = {"SENDGRID_API_KEY": _sendgrid_key}
    ACCOUNT_EMAIL_VERIFICATION = "mandatory"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    ACCOUNT_EMAIL_VERIFICATION = "optional"

# ─────────────────────────────────────────────────────────────
# Sentry — only initialise when DSN is provided
# ─────────────────────────────────────────────────────────────
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=0.2,
        send_default_pii=False,
        environment="production",
    )

# Production logging — JSON to stdout for Render's log aggregator
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
