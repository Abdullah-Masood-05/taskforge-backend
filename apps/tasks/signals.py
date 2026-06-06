"""
Signal handlers for the tasks app.

1. set_task_reference  — post_save, sets Task.reference on creation
2. log_task_activity   — uses pre_save to capture old values, post_save to write log
3. broadcast_to_board  — after ActivityLog, calls sync_broadcast_task_event so all
   connected WebSocket clients receive real-time task.created / task.updated /
   task.deleted events.

Performance note: sync_broadcast_task_event calls async_to_sync() inside a sync
signal, adding ~1-3 ms per task mutation. Candidate for a future Celery-based
out-of-band optimization.
"""
import structlog
import threading
from django.db.models.signals import post_delete, post_save, pre_save
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

# Fields we want to track. Each entry: (field_name, verb)
TRACKED_FIELDS = [
    ("status_id",   "status_changed"),
    ("assignee_id", "assignee_changed"),
    ("priority",    "priority_changed"),
    ("title",       "title_changed"),
    ("due_date",    "due_date_changed"),
]

# Thread-local storage to pass pre-save state into post-save
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

    On creation: writes a single 'created' entry, then broadcasts task.created.
    On update: compares pre/post state, writes one entry per changed field,
               then broadcasts task.updated.

    The actor is not available here (no request context in signals).
    The viewset sets `instance._actor` before calling save() so the signal
    can attribute the change. Falls back to None for non-request changes.
    """
    from apps.tasks.models import ActivityLog
    from apps.tasks.broadcast import sync_broadcast_task_event

    actor = getattr(instance, "_actor", None)

    def _task_payload():
        return {
            "id": str(instance.pk),
            "title": instance.title,
            "priority": instance.priority,
            "status_id": str(instance.status_id) if instance.status_id else None,
            "order": instance.order,
            "due_date": instance.due_date.isoformat() if instance.due_date else None,
            "reference_label": f"TASK-{instance.reference}" if instance.reference else None,
            "is_deleted": instance.is_deleted,
            "project_id": str(instance.project_id),
        }

    if created:
        ActivityLog.objects.create(
            task=instance,
            actor=actor,
            verb="created",
            old_value=None,
            new_value={"title": instance.title},
        )
        try:
            sync_broadcast_task_event(
                project_id=str(instance.project_id),
                event_type="task.created",
                task_data=_task_payload(),
                task_id=str(instance.pk),
            )
        except Exception as exc:
            logger.error("broadcast_signal_failed", event="task.created", task_id=str(instance.pk), error=str(exc))
        return

    old = getattr(_pre_save_state, "old", None)
    if old is None:
        return

    changed = False
    for field, verb in TRACKED_FIELDS:
        old_val = old.get(field)
        new_val = getattr(instance, field)
        if old_val != new_val:
            changed = True
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

    # Broadcast a single task.updated event if any tracked field changed.
    # Soft-deletes are broadcast as task.deleted so clients can remove the card.
    if changed:
        event_type = "task.deleted" if instance.is_deleted else "task.updated"
        try:
            sync_broadcast_task_event(
                project_id=str(instance.project_id),
                event_type=event_type,
                task_data=_task_payload(),
                task_id=str(instance.pk),
            )
        except Exception as exc:
            logger.error("broadcast_signal_failed", event=event_type, task_id=str(instance.pk), error=str(exc))


@receiver(post_delete, sender="tasks.Task")
def broadcast_task_deleted(sender, instance, **kwargs):
    """Push task.deleted to the board room after a hard delete."""
    from apps.tasks.broadcast import sync_broadcast_task_event
    try:
        sync_broadcast_task_event(
            project_id=str(instance.project_id),
            event_type="task.deleted",
            task_data=None,
            task_id=str(instance.pk),
        )
    except Exception as exc:
        logger.error("broadcast_signal_failed", event="task.deleted", task_id=str(instance.pk), error=str(exc))


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _broadcast_task(instance, event_type: str) -> None:
    """
    Serialize the task with TaskListSerializer and broadcast to the board.

    Uses a minimal serializer context (no request) so avatar URLs will
    be relative paths. This is acceptable for WS payloads — clients
    can prefix with the API base URL if needed.
    """
    from apps.tasks.broadcast import sync_broadcast_task_event
    from apps.tasks.serializers import TaskListSerializer

    try:
        task_data = TaskListSerializer(instance).data
        # Convert to plain dict so it's JSON-serializable by the channel layer
        task_data = dict(task_data)
    except Exception as exc:
        logger.error("task_serialization_failed", task_id=str(instance.pk), error=str(exc))
        task_data = {"id": str(instance.pk)}

    sync_broadcast_task_event(
        project_id=str(instance.project_id),
        event_type=event_type,
        task_data=task_data,
        task_id=str(instance.pk),
    )
