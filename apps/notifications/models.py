"""
Notification and ExportJob models.

Notification — in-app notification with GenericForeignKey target.
ExportJob    — tracks async PDF report generation status.
"""
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """
    In-app notification for a user.

    Uses GenericForeignKey so the target can be any model (Task, Project, etc.).
    The `verb` field is a machine-readable action type; `description` is
    the human-readable message shown in the UI.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("recipient"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
        verbose_name=_("actor"),
    )

    verb = models.CharField(
        _("verb"),
        max_length=60,
        db_index=True,
        help_text=_("Machine-readable action: task_assigned, comment_added, welcome, etc."),
    )
    description = models.TextField(
        _("description"),
        help_text=_("Human-readable message shown in the notification dropdown."),
    )

    # GenericForeignKey to any model (Task, Project, Comment, …)
    target_ct = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("target content type"),
    )
    target_id = models.UUIDField(_("target ID"), null=True, blank=True)
    target = GenericForeignKey("target_ct", "target_id")

    is_read = models.BooleanField(_("read"), default=False, db_index=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read"], name="notif_recipient_read_idx"),
            models.Index(fields=["recipient", "-created_at"], name="notif_recipient_date_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.verb}] → {self.recipient.email}"


class ExportJob(models.Model):
    """
    Tracks the status of an async PDF report generation task.

    Lifecycle: pending → processing → completed / failed
    The frontend polls GET /reports/{id}/ until status is completed.
    """

    class Status(models.TextChoices):
        PENDING    = "pending",    _("Pending")
        PROCESSING = "processing", _("Processing")
        COMPLETED  = "completed",  _("Completed")
        FAILED     = "failed",     _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name=_("organization"),
    )
    project = models.ForeignKey(
        "tasks.Project",
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name=_("project"),
        null=True,
        blank=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name=_("requested by"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    file_key = models.CharField(
        _("file key"),
        max_length=500,
        blank=True,
        help_text=_("S3 object key or local path for the generated PDF."),
    )
    error = models.TextField(_("error"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("export job")
        verbose_name_plural = _("export jobs")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Export {self.id} ({self.status})"
