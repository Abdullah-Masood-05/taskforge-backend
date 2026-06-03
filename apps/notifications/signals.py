"""
Signal handlers for notifications.

1. User post_save  → welcome email + notification on creation
2. Task pre/post_save → assignment notification + email when assignee changes
"""
import structlog
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)

# Thread-local to hold pre-save assignee for comparison
import threading
_pre_save_assignee = threading.local()


@receiver(pre_save, sender="tasks.Task")
def capture_task_assignee_before_save(sender, instance, **kwargs):
    """Stash the old assignee_id so we can detect changes in post_save."""
    if instance.pk is None:
        _pre_save_assignee.old_assignee_id = None
        return
    try:
        old = sender.objects.values_list("assignee_id", flat=True).get(pk=instance.pk)
        _pre_save_assignee.old_assignee_id = old
    except sender.DoesNotExist:
        _pre_save_assignee.old_assignee_id = None


@receiver(post_save, sender="tasks.Task")
def notify_task_assignment(sender, instance, created, **kwargs):
    """
    When a task is assigned (or reassigned), create an in-app notification
    and queue an email.
    """
    from apps.notifications.models import Notification
    from apps.notifications.tasks import send_task_assignment_email

    actor = getattr(instance, "_actor", None)
    new_assignee_id = instance.assignee_id

    if not new_assignee_id:
        return

    if created:
        # New task with an assignee — notify them
        old_assignee_id = None
    else:
        old_assignee_id = getattr(_pre_save_assignee, "old_assignee_id", None)
        if old_assignee_id == new_assignee_id:
            return  # Assignee didn't change

    # Don't notify yourself
    if actor and str(actor.id) == str(new_assignee_id):
        return

    ref = f"TASK-{instance.reference}" if instance.reference else str(instance.id)[:8]
    actor_name = (actor.full_name or actor.email) if actor else "Someone"

    Notification.objects.create(
        recipient_id=new_assignee_id,
        actor=actor,
        verb="task_assigned",
        description=f"{actor_name} assigned you to {ref}: {instance.title}",
        target_ct=ContentType.objects.get_for_model(sender),
        target_id=instance.pk,
    )
    logger.info(
        "notification_created",
        verb="task_assigned",
        recipient_id=str(new_assignee_id),
        task_id=str(instance.pk),
    )

    # Queue email
    send_task_assignment_email.delay(
        str(instance.pk),
        str(new_assignee_id),
        str(actor.id) if actor else None,
    )


@receiver(post_save, sender="accounts.User")
def notify_user_welcome(sender, instance, created, **kwargs):
    """
    On user registration, create a welcome notification and queue a welcome email.
    """
    if not created:
        return

    from apps.notifications.models import Notification
    from apps.notifications.tasks import send_welcome_email

    Notification.objects.create(
        recipient=instance,
        actor=None,
        verb="welcome",
        description="Welcome to TaskForge! Create your first organization to get started.",
    )

    send_welcome_email.delay(str(instance.pk))
    logger.info("welcome_notification_created", user_id=str(instance.pk))
