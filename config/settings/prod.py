"""
Production settings — strict security, S3 storage, SendGrid email, Sentry.
"""
from .base import *  # noqa: F401, F403
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration

DEBUG = False

# Security headers
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# AWS S3 for static and media
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
STATICFILES_STORAGE = "storages.backends.s3boto3.S3StaticStorage"

# Email via SendGrid (anymail)
EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
ANYMAIL = {
    "SENDGRID_API_KEY": env("SENDGRID_API_KEY"),  # noqa: F405
}
ACCOUNT_EMAIL_VERIFICATION = "mandatory"

# Sentry
_sentry_dsn = env("SENTRY_DSN", default="")  # noqa: F405
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

# Production logging — JSON to stdout for log aggregators
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
