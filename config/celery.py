"""
Celery application entry point.
Referenced by config/__init__.py so Celery is loaded when Django starts.
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("taskforge")

# Read Celery config from Django settings (CELERY_* prefix)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# ── Beat schedule (periodic tasks) ───────────────────────────────────────────
app.conf.beat_schedule = {
    # Daily digest email at 08:00 UTC every day
    "daily-digest": {
        "task": "apps.notifications.tasks.send_daily_digest",
        "schedule": crontab(hour=8, minute=0),
    },
}
app.conf.timezone = "UTC"


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
