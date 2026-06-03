"""
Expose the Celery app here so that Django loads it when the module is imported.
Required for auto-discovery of tasks in installed apps.
"""
from .celery import app as celery_app  # noqa: F401

__all__ = ["celery_app"]
