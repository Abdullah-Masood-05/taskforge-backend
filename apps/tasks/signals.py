"""
Signal handlers for the tasks app.

1. set_task_reference  — post_save, sets Task.reference on creation
2. log_task_activity   — uses pre_save to capture old values, post_save to write log
"""
import structlog
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# 1. Auto-assign per-project sequential reference
# ─────────────────────────────────────────────────────────────

@receiver(post_save, sender="tasks.Task")
def set_task_reference(sender, instance, created, **kwargs):
    """
    Assign a sequential reference integer to new tasks.

    Uses SELECT MAX(reference) + 1 within the project to avoid relying on
    DB auto-increment (which would require a separate sequence per project).
    The update is done with update_fields to avoid triggering this signal again.
    """
    if created and instance.reference is None:
        from django.db.models import Max
        max_ref = (
            sender.objects.filter(project=instance.project)
            .exclude(pk=instance.pk)
            .aggregate(m=Max("reference"))["m"]
        )
        instance.reference = (max_ref or 0) + 1
        sender.objects.filter(pk=instance.pk).update(reference=instance.reference)
        logger.debug(
            "task_reference_assigned",
            task_id=str(instance.pk),
            reference=instance.reference,
        )


# ─────────────────────────────────────────────────────────────
# 2. ActivityLog — capture changes via pre/post save pair
# ─────────────────────────────────────────────────────────────

# Fields we want to track. Each entry: (field_name, verb, display_func)
TRACKED_FIELDS = [
    ("status_id",  "status_changed"),
    ("assignee_id","assignee_changed"),
    ("priority",   "priority_changed"),
    ("title",      "title_changed"),
    ("due_date",   "due_date_changed"),
]

# Thread-local storage to pass pre-save state into post-save
import threading
_pre_save_state = threading.local()


@receiver(pre_save, sender="tasks.Task")
def capture_pre_save_state(sender, instance, **kwargs):
    """
    Fetch and stash the current DB state before the save happens.
    Skipped for new instances (no DB row yet).
    """
    if instance.pk is None:
        _pre_save_state.old = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        _pre_save_state.old = {field: getattr(old, field) for field, _ in TRACKED_FIELDS}
    except sender.DoesNotExist:
        _pre_save_state.old = None


@receiver(post_save, sender="tasks.Task")
def log_task_activity(sender, instance, created, **kwargs):
    """
    Write ActivityLog entries for tracked field changes.

    On creation: writes a single 'created' entry.
    On update: compares pre/post state, writes one entry per changed field.

    The actor is not available here (no request context in signals).
    The viewset sets `instance._actor` before calling save() so the signal
    can attribute the change. Falls back to None for non-request changes.
    """
    from apps.tasks.models import ActivityLog

    actor = getattr(instance, "_actor", None)

    if created:
        ActivityLog.objects.create(
            task=instance,
            actor=actor,
            verb="created",
            old_value=None,
            new_value={"title": instance.title},
        )
        return

    old = getattr(_pre_save_state, "old", None)
    if old is None:
        return

    for field, verb in TRACKED_FIELDS:
        old_val = old.get(field)
        new_val = getattr(instance, field)
        if old_val != new_val:
            ActivityLog.objects.create(
                task=instance,
                actor=actor,
                verb=verb,
                old_value={"value": str(old_val) if old_val is not None else None},
                new_value={"value": str(new_val) if new_val is not None else None},
            )
            logger.info(
                "task_activity_logged",
                task_id=str(instance.pk),
                verb=verb,
                old=str(old_val),
                new=str(new_val),
            )
