"""
Signal handlers for notifications.

1. User post_save  → welcome email + notification on creation
2. Task.assignees m2m_changed → assignment notification + email for each
   newly added assignee
"""
import structlog
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(m2m_changed, sender="tasks.Task_assignees")
def notify_task_assignment(sender, instance, action, reverse, pk_set, **kwargs):
    """
    When users are added to a task's assignees, create an in-app
    notification and queue an email for each of them (except the actor).
    """
    if reverse or action != "post_add" or not pk_set:
        return

    from apps.notifications.models import Notification
    from apps.notifications.tasks import send_task_assignment_email

    actor = getattr(instance, "_actor", None)
    ref = f"TASK-{instance.reference}" if instance.reference else str(instance.id)[:8]
    actor_name = (actor.full_name or actor.email) if actor else "Someone"
    task_ct = ContentType.objects.get_for_model(type(instance))

    for assignee_id in pk_set:
        # Don't notify yourself
        if actor and str(actor.id) == str(assignee_id):
            continue

        Notification.objects.create(
            recipient_id=assignee_id,
            actor=actor,
            verb="task_assigned",
            description=f"{actor_name} assigned you to {ref}: {instance.title}",
            target_ct=task_ct,
            target_id=instance.pk,
        )
        logger.info(
            "notification_created",
            verb="task_assigned",
            recipient_id=str(assignee_id),
            task_id=str(instance.pk),
        )

        # Queue email
        send_task_assignment_email.delay(
            str(instance.pk),
            str(assignee_id),
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
